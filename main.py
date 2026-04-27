from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from typing import Dict
from kyc_auth import kyc_auth
from sqlmodel import Session, create_engine, select, col, text
import orm
from dotenv import load_dotenv
import os

# Setup db stuff
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

app = FastAPI()

# Helper function for getting session
def db_init():
  with Session(engine) as session:
    yield session

# device_id -> WebSocket of precinctOfficer.
precinct_officer: Dict[str, WebSocket] = {}

class ScanRequest(BaseModel):
  device_id: str
  qr: dict

# ----- API Endpoints -----

# /scan is called by ESP8266 to send decoded QR to server.
# Then, kyc_auth the decoded QR data
# Then, send kyc_auth response to corresponding precinct_officer 
@app.post("/scan")
async def scan(payload: ScanRequest):
  device_id = payload.device_id

  # If PrecinctOfficer's local machine is not connected, raise an error to ESP
  if device_id not in precinct_officer:
    raise HTTPException(
      status_code=500,
      detail="PrecinctOfficer's local machine is not connected. Please try again after connecting it."
    )

  try:
    # MOSIP Response from kyc_auth.py
    uin: str = payload.qr.get("uin", None)
    dob: str = payload.qr.get("dob", None)
    if uin == None or dob == None:
      raise Exception("QR missing UIN or DOB. Cannot authenticate")
    mosip_response = kyc_auth(uin, dob)

    # Perform crosschecks with Cast Voter Database
    # Also send results to PrecinctOfficer
    with Session(engine) as session:
      voter: orm.Voter = session.exec(
        select(orm.Voter.uin, orm.Voter.precinct, orm.Voter.voted)
        .where(orm.Voter.uin == uin)
      ).first()
    
      voter_response = {
        "registered": voter is not None, 
        "precinct": voter.precinct if voter else None,
        "voted": voter.voted if voter else False
      }

  except Exception as e:
    # Display error on PrecinctOfficer's screen
    await precinct_officer[device_id].send_json({"error": str(e)})
    # HTTP Response to ESP
    raise HTTPException(
      status_code=500,
      detail=str(e)
    )

  # Assuming everything is a success, display the MOSIP and voter checks on PrecinctOfficer's screen
  response = {
     "uin": mosip_response["uin"],
     "demographics": mosip_response["demographics"],
     "photo": mosip_response["photo"],
     "registered_voter": voter_response["registered"],
     "precinct": voter_response["precinct"],
     "voted": voter_response["voted"]
  } 
  await precinct_officer[device_id].send_json(response)
  # HTTP Response to ESP
  return {
    "status": "sent", 
    "device_id": device_id, 
  }
  
# /display-pic/{device_id} is called by the PrecinctOfficer.
# It uses a WebSocket to detect incoming data needed to be displayed.
# Data is MOSIP ID data from /scan.
@app.websocket("/display-pic/{device_id}")
async def display_pic(websocket: WebSocket, device_id: str):
  await websocket.accept()

  if device_id not in precinct_officer:
    precinct_officer[device_id] = websocket
  
  try:
    while True:
      await websocket.receive_text()
  except WebSocketDisconnect:
    precinct_officer.pop(device_id, None)

"""
NOTES for /ballot:
    - City and province names must match exactly what's in the database for now. 
    Maybe we can have a better way to handle inconsistent names later e.g. Manila City vs. Manila vs. City of Manila
"""

# TODO: change this to websocket (used GET for now)
# /ballot is called by PrecinctOfficer once voter's identity is confirmed
# Websocket is used to detect incoming data containing confirmation from the PrecintOfficer,
# Once received, the server will send back the ballot data for that voter's city and province.
# City and province names must match exactly what's in the database for now. 
# Maybe we can have a better way to handle inconsistent names later e.g. Manila City vs. Manila vs. City of Manila 
@app.get("/ballot")
async def get_ballot(province: str, city: str):
    with Session(engine) as session:
        # Retrieve the province and city ids based on their names
        provID = session.exec(
            select(Province.province_id).where(col(Province.province_name).ilike(province))
        ).first()
        if not provID:
            raise HTTPException(status_code=404, detail=f"Province not found: {province}")

        cityID = session.exec(
            select(City.city_id).where(
                col(City.city_name).ilike(city),
                City.province_id == provID
            )
        ).first()
        if not cityID:
            raise HTTPException(status_code=404, detail=f"City not found: {city}")

        # Get all candidates
        results = session.exec(
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