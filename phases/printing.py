from fastapi import HTTPException
from sqlmodel import Session, select, col

from orm import Province, City, Candidate, Position, Scope

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
        .order_by(Scope.scope_id, Position.position_id, Candidate.candidate_number)
    ).all()

    # Group by position
    ballot = {}
    for candidate, position, scope in results:
        pos_name = position.position_name
        if pos_name not in ballot:
            ballot[pos_name] = {
                "position_id": position.position_id,
                "title": position.position_name,
                "vote_for": position.max_votes,
                "scope": scope.scope_name,
                # Some fields from dale's sample ballot, can be changed later
                "instruction_en": f"Vote for {position.max_votes}",
                "instruction_tl": f"Bumoto ng hindi hihigit sa {position.max_votes}",
                "candidates": [],
            }
        ballot[pos_name]["candidates"].append({
            # TODO: add candidate number and party later
            "id": candidate.candidate_id,
            "name": candidate.candidate_name,
            "number": candidate.candidate_number,
            "party": candidate.party if candidate.party else "Independent",
        })

    return {
        "election": {
            "title": "2024 National and Local Elections",
            "date": "2025-05-12",
            # We don't have a way to determine the voter's precinct, so we'll just hardcode it for now.
            # "precinct_id": "90020001",
            # "precinct_cluster": "0077A",
            "province": province,
            "city": city,

        },
        "positions": list(ballot.values()),
    }