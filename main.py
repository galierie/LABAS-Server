from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Response
from pydantic import BaseModel
from typing import Dict
from kyc_auth import kyc_auth
from sqlmodel import Session, create_engine, select, col, text, update, delete
import orm
from dotenv import load_dotenv
import os
from fastapi.middleware.cors import CORSMiddleware

from phases import printing

# Setup db stuff
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

app = FastAPI()

# Allow CORS for local development. This allows the webapp running on localhost to make a GET request to the server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for dev only — see below for prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
import subprocess
VM_PORT = "6310"
PRINTER = "Brother_MFC_T800W"

@app.get("/print-ballot")
async def print_ballot(province: str, city: str, uin: str, db: Session = Depends(db_init)):
  ballot_data = printing.get_ballot_data(db=db, province=province, city=city)
  pdf_content = printing.build_ballot(ballot_data=ballot_data, uin=uin, db=db)

  result = subprocess.run([
    "lp", "-h", f"localhost:{VM_PORT}", "-d", PRINTER
  ], input=pdf_content, capture_output=True, timeout=30)
  if result.returncode == 0:
    print("Ballot sent to printer successfully.")

    voter = db.exec(select(orm.Voter).where(orm.Voter.uin == uin)).first()
  
    # If valid voter, write in database the precint they generated the ballot
    # for now, this is hardcoded to 'UP Diliman'
    voter.precinct = "UP Diliman"
    db.add(voter)
    db.commit()
    db.refresh(voter)

    return {"status": "printed"}
  else:
    print(f"Error: {result.stderr.decode()}")
    return {"status": "failed"}

# Given a UIN of a voter, return the candidate-coordinate mapping of his ballot.
# This is called by PrecinctOfficer.
@app.get("/get-ballot-template")
async def get_ballot_template(uin: str, db: Session = Depends(db_init)):
  ballot_coordinates: list[orm.Bubble_Coordinate] = db.exec(
    select(orm.Bubble_Coordinate)
    .where(orm.Bubble_Coordinate.uin == uin)
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

class TallyRequest(BaseModel):
  uin: str
  candidate_ids: list[int]

# This API is used to add a voter's votes into the tally count.
# This will also delete the voter's entries in the bubble_coordinates table.
@app.post("/tally")
async def get_ballot_template(request: TallyRequest, db: Session = Depends(db_init)):
  # Consider this as one transaction
  with db.begin():
    
    # Increment votecounts
    for candidate_id in request.candidate_ids:
      db.exec(
        update(orm.Tally)
        .where(orm.Tally.candidate_id == candidate_id)
        .values(votecount=orm.Tally.votecount + 1)
      )

    # Delete bubble_coordinates entries of voter
    db.exec(
      delete(orm.Bubble_Coordinate)
      .where(orm.Bubble_Coordinate.uin == request.uin)
    )
  
  return {"status": "added to tally"}
    
