"""
Helper functions for the printing phase.
"""

from datetime import date
from fastapi import HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select, col

from orm import Province, City, Candidate, Position, Scope

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

def get_ballot(db: Session, province: str, city: str):
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
