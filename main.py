from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Response
from pydantic import BaseModel
from typing import Dict
from kyc_auth import kyc_auth
from sqlmodel import Session, create_engine, select, col, text
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

  # Check if the registered voter
    voter = db.exec(select(Voter).where(Voter.uin == mosip_response["uin"])).first()
    # Don't allow voter if not registered, already voted, or have claimed the ballot in another precint
    if not voter:
        raise HTTPException(status_code=404, detail="Invalid voter")    
    elif voter.voted == True:
        raise HTTPException(status_code=409, detail="Voter has already voted")    
    elif voter.precinct == None:
        raise HTTPException(status_code=403, detail=f"Voter already claimed ballot in precinct {voter.precinct}")    

  
  # If valid voter, write in database the precint they generated the ballot
  # for now, this is hardcoded to 'UP Diliman'
  voter.precinct = "UP Diliman"
  db.add(voter)
  db.commit()
  db.refresh(voter)

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
async def print_ballot(province: str, city: str, db: Session = Depends(db_init)):
  ballot_data = printing.get_ballot_data(db=db, province=province, city=city)
  pdf_content = printing.build_ballot(ballot_data=ballot_data)

  result = subprocess.run([
    "lp", "-h", f"localhost:{VM_PORT}", "-d", PRINTER
  ], input=pdf_content, capture_output=True, timeout=30)
  if result.returncode == 0:
      print("Ballot sent to printer successfully.")
  else:
      print(f"Error: {result.stderr.decode()}")

  return {"status": "printed"}