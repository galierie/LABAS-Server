"""
Helper functions for the printing phase.
"""

from datetime import date, datetime
from fastapi import HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select, col


from functools import partial
from io import BytesIO
from math import ceil
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import registerFont, registerFontFamily # type: ignore
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    PageTemplate,
    Frame,
    Spacer,
    Paragraph,
    Flowable,
)


from orm import Province, City, Candidate, Position, Scope, Bubble_Coordinate


from phases.print_constants import (
    PAGE_SIZE,
    PAGE_MARGIN,
    PAGE_WIDTH,
    PAGE_HEIGHT,
    TITLE_SPACING,
    MARKER_POSITIONS,
    MARKER_SIZE,
    N_COLS,
    BUBBLE_RADIUS,
    BUBBLE_SPACING,
    mm,
)
PDF_PATH = 'ballot.pdf'

from pprint import pprint

# Getting Ballot Data

class CandidateBallotData(BaseModel):
    id: int
    first_name: str
    last_name: str
    middle_name: str
    party: str

class PositionBallotData(BaseModel):
    position_id: int
    title: str
    max_votes: int
    scope: str
    candidates: list[CandidateBallotData]

class ElectionData(BaseModel):
    title: str
    date: str
    province: str
    city: str

class BallotData(BaseModel):
    election: ElectionData
    positions: list[PositionBallotData]

def get_ballot_data(db: Session, province: str, city: str) -> BallotData:
    # Retrieve the province and city ids based on their names
    provID = db.exec(
        select(Province.province_id).where(col(Province.province_name).ilike(province))
    ).first()
    if not provID:
        raise HTTPException(status_code=404, detail=f"Province not found: {province}")

    cityID = db.exec(
        select(City.city_id).where(
            col(City.city_name).ilike(city),
            City.province_id == provID
        )
    ).first()
    if not cityID:
        raise HTTPException(status_code=404, detail=f"City not found: {city}")

    # Get all candidates
    results = db.exec(
        select(Candidate, Position, Scope)
        .join(Position, Candidate.position_id == Position.position_id)
        .join(Scope, Position.scope_id == Scope.scope_id)
        .where(
            (Scope.scope_id == 1) |
            ((Scope.scope_id == 2) & (Candidate.province_id == provID)) |
            ((Scope.scope_id == 3) & (Candidate.city_id == cityID))
        )
        .order_by(Scope.scope_id, Position.position_id, Candidate.last_name, Candidate.first_name, Candidate.middle_name)
    ).all()

    # Group by position
    ballot: dict[str, PositionBallotData] = dict()
    for candidate, position, scope in results:
        pos_name = position.position_name
        if pos_name not in ballot:
            temp_candidates: list[CandidateBallotData] = []
            ballot[pos_name] = PositionBallotData.model_validate({
                "position_id": position.position_id,
                "title": position.position_name,
                "max_votes": position.max_votes,
                "scope": scope.scope_name,
                "candidates": temp_candidates,
            })
        ballot[pos_name].candidates.append(CandidateBallotData.model_validate({
            # TODO: add party later
            "id": candidate.candidate_id,
            "first_name": candidate.first_name,
            "last_name": candidate.last_name,
            "middle_name": candidate.middle_name,
            "party": candidate.party if candidate.party else "Independent",
        }))

    # Determine candidate order by name. This determines candidate number.
    def get_candidate_order(candidate: CandidateBallotData):
        return (candidate.last_name, candidate.first_name, candidate.middle_name)

    for pos_name in ballot:
        ballot[pos_name].candidates.sort(key=get_candidate_order)

    # Get election info
    today = date.today()
    election_data = ElectionData.model_validate({
        "title": f"{today.strftime('%Y')} National and Local Elections",
        "date": today.strftime('%Y-%m-%d'),
        "province": province,
        "city": city,
    })

    return BallotData(election=election_data, positions=list(ballot.values()))



# Printing Ballot Data

# needed to have ñ in PDF (for Filipino names)
registerFont(TTFont('NotoSans', 'fonts/NotoSans-Regular.ttf'))
registerFont(TTFont('NotoSans-Bold', 'fonts/NotoSans-Bold.ttf'))
registerFont(TTFont('NotoSans-Italic', 'fonts/NotoSans-Italic.ttf'))
registerFont(
    TTFont('NotoSans-BoldItalic', 'fonts/NotoSans-BoldItalic.ttf'))
registerFontFamily('NotoSans',
                   normal='NotoSans',
                   bold='NotoSans-Bold',
                   italic='NotoSans-Italic',
                   boldItalic='NotoSans-BoldItalic'
                   )

class BubbleCoords(CandidateBallotData):
    position: str
    bubble_x_pt: float
    bubble_y_pt: float
    page: int

# Helper function to store UIN's ballot's bubble coordinates
def save_bubble_coordinates(bubble_coords: list[BubbleCoords], uin: str, db: Session):
    orm_bubble_coords: list[Bubble_Coordinate] = [
        Bubble_Coordinate(
            uin=uin,
            candidate_id=b.id,
            bubble_x_pt=b.bubble_x_pt,
            bubble_y_pt=b.bubble_y_pt,
            page=b.page
        )
        for b in bubble_coords
    ]

    db.add_all(orm_bubble_coords)
    db.commit()

class CandidateGrid(Flowable):
    def __init__(
        self,
        candidates: list[CandidateBallotData],
        position: str,
        bubble_coords: list[BubbleCoords],
        n_cols:int=N_COLS,
        bubble_radius:float=BUBBLE_RADIUS,
        font_name:str="NotoSans",
        font_size:int=6,
        max_lines:int=2,
    ):
        Flowable.__init__(self)
        self.candidates = candidates
        self.position = position
        self.bubble_coords = bubble_coords
        self.n_cols = n_cols
        self.bubble_radius = bubble_radius
        self.max_lines = max_lines

        self.text_style = ParagraphStyle(
            name="CandidateName",
            fontName=font_name,
            fontSize=font_size,
            leading=font_size + 2,
            textColor=colors.black,
        )

        self.row_height = self.text_style.leading * max_lines + 2 * mm

    # computes the size of the grid
    def wrap(self, aW: float, aH: float):
        self._column_width = aW / self.n_cols
        self._rows_per_col = ceil(
            len(self.candidates) / self.n_cols)
        self._text_width = self._column_width - \
            (2 * self.bubble_radius + BUBBLE_SPACING + 1 * mm)
        self.width = aW
        self.height = self.row_height * self._rows_per_col
        return (self.width, self.height)

    def draw(self):
        canvas = self.canv
        for idx, candidate in enumerate(self.candidates):
            # get column and row
            col = idx // self._rows_per_col
            row = idx % self._rows_per_col

            # calculate position
            x_col = col * self._column_width
            y_row_top = self.height - row * self.row_height
            y_row_bottom = y_row_top - self.row_height
            y_center = y_row_top - self.row_height / 2

            # draw box
            canvas.saveState()
            canvas.setLineWidth(0.4)
            canvas.rect(x_col, y_row_bottom, self._column_width,
                        self.row_height, fill=0, stroke=1)
            canvas.restoreState()

            # draw bubble
            bubble_x = x_col + self.bubble_radius + 1 * mm
            bubble_y = y_center
            canvas.setFillColorRGB(1, 1, 1)
            canvas.circle(bubble_x, bubble_y,
                          self.bubble_radius, fill=0, stroke=1)

            # write candidate
            # no candidate name means it's a party list
            # Filipinos may or may not have a middle name
            if len(candidate.last_name) == 0 and len(candidate.first_name) == 0:
                label = f"{idx}. {candidate.party.upper()}"
            else:
                label = f"{idx}. {candidate.last_name.upper()}, {candidate.first_name.upper()}{f' {candidate.middle_name[0].upper()}.' if len(candidate.middle_name) > 0 else ''} ({candidate.party.upper()})"
            candidate_name = Paragraph(label, self.text_style)

            text_x = bubble_x + self.bubble_radius + BUBBLE_SPACING
            _, candidate_height = candidate_name.wrap(
                self._text_width, self.row_height)
            text_y = y_row_bottom + (self.row_height - candidate_height) / 2
            candidate_name.drawOn(canvas, text_x, text_y)

            # calculate absolute position to pass to OMR
            abs_x, abs_y = canvas.absolutePosition(bubble_x, bubble_y)
            self.bubble_coords.append(BubbleCoords.model_validate({
                "position": self.position,
                "id": candidate.id, # Map to candidate id instead
                "last_name": candidate.last_name,
                "first_name": candidate.first_name,
                "middle_name": candidate.middle_name,
                "party": candidate.party,
                "bubble_x_pt": abs_x,
                "bubble_y_pt": abs_y,
                "page": canvas.getPageNumber(),
            }))

def init_ballot(canvas: Canvas, doc: BaseDocTemplate, election_data: ElectionData):
    canvas.saveState()
    canvas.setFont("NotoSans-Bold", 14)

    # Draw OMR Markers
    for (x, y) in MARKER_POSITIONS:
        canvas.rect(x, y, MARKER_SIZE, MARKER_SIZE, fill=1, stroke=0)

    # Write general election information
    title_y = PAGE_HEIGHT - PAGE_MARGIN / 2 - 5 * mm
    canvas.drawCentredString(PAGE_WIDTH / 2, title_y, election_data.title)

    canvas.setFont("NotoSans", 11)
    election_date = datetime.strptime(election_data.date, '%Y-%m-%d')
    canvas.drawCentredString(PAGE_WIDTH / 2, title_y - 5 * mm, election_date.strftime('%B %d, %Y'))
    canvas.drawCentredString(PAGE_WIDTH / 2, title_y - 10 * mm, f'{election_data.city}, {election_data.province}')

    canvas.restoreState()

def build_ballot(ballot_data: BallotData, uin: str, db: Session) -> bytes:
    # Make the page frame
    frame = Frame(
        PAGE_MARGIN,
        PAGE_MARGIN,
        PAGE_WIDTH - 2 * PAGE_MARGIN,
        PAGE_HEIGHT - 2 * PAGE_MARGIN - TITLE_SPACING,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="main",
    )

    # Save to IO buffer, not to disk, to enable return from API route
    buffer = BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=PAGE_SIZE)

    init_ballot_with_election_data = partial(init_ballot, election_data=ballot_data.election)
    doc.addPageTemplates([
        PageTemplate(id="ballot", frames=[frame], onPage=init_ballot_with_election_data),
    ])

    # Write position-specific information

    header_style = ParagraphStyle(
        name="PositionHeader",
        fontName="NotoSans-Bold",
        fontSize=12,
        spaceAfter=3,
        alignment=TA_CENTER,
        textColor=colors.black,
    )

    instruction_style = ParagraphStyle(
        name="PositionInstruction",
        fontName="NotoSans",
        fontSize=8,
        spaceAfter=3,
        alignment=TA_CENTER,
        textColor=colors.black,
    )

    bubble_coords: list[BubbleCoords] = []
    story: list[Paragraph | Spacer | Flowable] = []

    for position in ballot_data.positions:
        # title + max_votes
        story.append(Paragraph(position.title.upper(), header_style))
        story.append(Paragraph(f'Vote for {position.max_votes}', instruction_style))
        story.append(Spacer(1, 2 * mm))

        # candidates
        story.append(CandidateGrid(position.candidates, position.title, bubble_coords))
        story.append(Spacer(1, 6 * mm))

    doc.build(story)

    # Get content
    pdf_content = buffer.getvalue()
    buffer.close()

    # print("Bubble Coords:")
    # pprint(bubble_coords)

    # Save bubble_cords into database so we could retrive them given a UIN in /get-ballot-template.
    save_bubble_coordinates(bubble_coords, uin, db)

    return pdf_content

# Given a UIN of a voter, return the candidate-coordinate mapping of his ballot.
# This is a helper function. Used by /submit-ballot
from phases.omr_scanner import BubbleCoordinate
def get_ballot_template(uin: str, db: Session) -> list[BubbleCoordinate]:
  ballot_coordinates: list[Bubble_Coordinate] = db.exec(
    select(Bubble_Coordinate)
    .where(Bubble_Coordinate.uin == uin)
  ).all()

  return [
    {
      "candidate_id": row.candidate_id,
      "bubble_x_pt": row.bubble_x_pt,
      "bubble_y_pt": row.bubble_y_pt,
      "page": row.page
    }
    for row in ballot_coordinates
  ]