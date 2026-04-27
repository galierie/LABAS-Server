from sample import senators, mayors, vice_mayors
from reportlab.platypus import (
    BaseDocTemplate,
    PageTemplate,
    Frame,
    Flowable,
    Spacer,
    Paragraph,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from constants import (
    A4,
    PAGE_MARGIN,
    PAGE_WIDTH,
    PAGE_HEIGHT,
    N_COLS,
    BUBBLE_RADIUS,
    BUBBLE_SPACING,
    MARKER_SIZE,
    MARKER_POSITIONS,
    TITLE_SPACING,
    BALLOT_TITLE,
    mm
)
from math import ceil

# needed to have ñ in PDF (for Filipino names)
pdfmetrics.registerFont(TTFont('NotoSans', 'fonts/NotoSans-Regular.ttf'))
pdfmetrics.registerFont(TTFont('NotoSans-Bold', 'fonts/NotoSans-Bold.ttf'))
pdfmetrics.registerFont(TTFont('NotoSans-Italic', 'fonts/NotoSans-Italic.ttf'))
pdfmetrics.registerFont(
    TTFont('NotoSans-BoldItalic', 'fonts/NotoSans-BoldItalic.ttf'))
registerFontFamily('NotoSans',
                   normal='NotoSans',
                   bold='NotoSans-Bold',
                   italic='NotoSans-Italic',
                   boldItalic='NotoSans-BoldItalic'
                   )


def init_ballot(canvas, doc):
    canvas.saveState()
    canvas.setFont("NotoSans-Bold", 14)

    for (x, y) in MARKER_POSITIONS:
        canvas.rect(x, y, MARKER_SIZE, MARKER_SIZE, fill=1, stroke=0)

    title_y = PAGE_HEIGHT - PAGE_MARGIN / 2 - 5 * mm
    canvas.drawCentredString(PAGE_WIDTH / 2, title_y, BALLOT_TITLE)
    canvas.restoreState()


class CandidateGrid(Flowable):
    def __init__(
        self,
        candidates,
        position,
        bubble_coords,
        n_cols=N_COLS,
        bubble_radius=BUBBLE_RADIUS,
        font_name="NotoSans",
        font_size=8,
        max_lines=2,
    ):
        Flowable.__init__(self)
        self.candidates = candidates
        self.position = position
        self.bubble_coords = bubble_coords
        self.n_cols = n_cols
        self.bubble_radius = bubble_radius
        self.font_name = font_name
        self.font_size = font_size
        self.max_lines = max_lines

        self.text_style = ParagraphStyle(
            name="CandidateName",
            fontName=self.font_name,
            fontSize=self.font_size,
            leading=self.font_size + 2,
            textColor=(0, 0, 0),
        )

        self.row_height = self.text_style.leading * max_lines + 2 * mm

    # computes the size of the grid
    def wrap(self, avail_width, avail_height):
        self._column_width = avail_width / self.n_cols
        self._rows_per_col = ceil(
            len(self.candidates) / self.n_cols)
        self._text_width = self._column_width - \
            (2 * self.bubble_radius + BUBBLE_SPACING + 1 * mm)
        self.width = avail_width
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
            if candidate['party'] == "PARTY-LIST":
                label = f"{candidate['number']}. {candidate['name']}"
            else:
                label = f"{candidate['number']}. {
                    candidate['name']} ({candidate['party']})"
            candidate_name = Paragraph(label, self.text_style)

            text_x = bubble_x + self.bubble_radius + BUBBLE_SPACING
            _, candidate_height = candidate_name.wrap(
                self._text_width, self.row_height)
            text_y = y_row_bottom + (self.row_height - candidate_height) / 2
            candidate_name.drawOn(canvas, text_x, text_y)

            # calculate absolute position to pass to OMR
            abs_x, abs_y = canvas.absolutePosition(bubble_x, bubble_y)
            self.bubble_coords.append({
                "position": self.position,
                "number": candidate["number"],
                "name": candidate["name"],
                "party": candidate["party"],
                "bubble_x_pt": abs_x,
                "bubble_y_pt": abs_y,
                "page": canvas.getPageNumber(),
            })


def build_ballot(ballot_data, pdf_path="ballot.pdf"):
    frame = Frame(
        PAGE_MARGIN,
        PAGE_MARGIN,
        PAGE_WIDTH - 2 * PAGE_MARGIN,
        PAGE_HEIGHT - 2 * PAGE_MARGIN - TITLE_SPACING,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="main",
    )

    doc = BaseDocTemplate(pdf_path, pagesize=A4)
    doc.addPageTemplates([
        PageTemplate(id="ballot", frames=[frame], onPage=init_ballot),
    ])

    header_style = ParagraphStyle(
        name="PositionHeader",
        fontName="NotoSans-Bold",
        fontSize=12,
        spaceAfter=3,
        alignment=TA_CENTER,
    )

    bubble_coords = []
    story = []

    for position, candidates in ballot_data.items():
        story.append(Paragraph(position, header_style))
        story.append(Spacer(1, 2 * mm))
        story.append(CandidateGrid(candidates, position, bubble_coords))
        story.append(Spacer(1, 6 * mm))

    doc.build(story)

    print(bubble_coords)
    return pdf_path
