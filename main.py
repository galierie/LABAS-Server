from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Response
from pydantic import BaseModel
from typing import Any, Dict, Optional
from collections import defaultdict
from enum import Enum
from kyc_auth import kyc_auth
from sqlmodel import Session, create_engine, select, col, text, update, delete, func, and_, or_
import orm
from dotenv import load_dotenv
import os
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import base64

from phases import printing
from phases.omr_scanner import BubbleCoordinate, OMRInputData, check_page

# Setup db stuff
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL is None:
  raise HTTPException(status_code=500, detail="Missing database URL.")
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

DUMMY_DATA = {
  "mikel": {
     "uin": "2054873096",# mosip_response["uin"],
     "demographics": {
        "location1_eng": "City of Pasig",
        "location3_eng": "Metropolitan Manila Second District",
     },# mosip_response["demographics"],
     "photo": "", #mosip_response["photo"],
     "precinct": "UP Diliman",# voter_response["precinct"],
     "voter_status": "printed",# voter_response["voter_status"],
  },
  "dale": {
     "uin": "9471253705",# mosip_response["uin"],
     "demographics": {
        "location1_eng": "City of Pasig",
        "location3_eng": "Metropolitan Manila Second District",
     },# mosip_response["demographics"],
     "photo": "", #mosip_response["photo"],
     "precinct": "UP Diliman",# voter_response["precinct"],
     "voter_status": "printed",# voter_response["voter_status"],
  },
  "lian": {
     "uin": "9039823146",# mosip_response["uin"],
     "demographics": {
        "location1_eng": "Angeles City",
        "location3_eng": "Pampanga",
     },# mosip_response["demographics"],
     "photo": "", #mosip_response["photo"],
     "precinct": "UP Diliman",# voter_response["precinct"],
     "voter_status": "tallied",# voter_response["voter_status"],
  },
  "miguel": {
     "uin": "8561086326",# mosip_response["uin"],
     "demographics": {
        "location1_eng": "Angeles City",
        "location3_eng": "Pampanga",
     },# mosip_response["demographics"],
     "photo": "", #mosip_response["photo"],
     "precinct": "",# voter_response["precinct"],
     "voter_status": None,# voter_response["voter_status"],
  },
    "yenyen": {
     "uin": "6523508751",# mosip_response["uin"],
     "demographics": {
        "location1_eng": "Quezon City",
        "location3_eng": "Metropolitan Manila Second District",
     },# mosip_response["demographics"],
     "photo": "", #mosip_response["photo"],
     "precinct": "",# voter_response["precinct"],
     "voter_status": None,# voter_response["voter_status"],
  },
}

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
      voter = session.exec(
        select(orm.Voter)
        .where(orm.Voter.uin == uin)
      ).first()
      if voter is None:
        raise HTTPException(status_code=400, detail="Voter is unregistered.")

      len_bubbles = session.exec(
        select(func.count(col(orm.Bubble_Coordinate.uin)))
        .where(orm.Bubble_Coordinate.uin == uin)
      ).one()
      
      voter_status: str | None = None
      # voter_statuses:
      #   None = precinct is None, no bubble_coords in db, not voted
      #   printed = precinct is not None, bubble_coords saved in db, not voted
      #   tallied = precinct is not None, no bubble_coords in db, voted
      if voter.precinct is not None:
        if len_bubbles > 0 and not voter.voted:
          voter_status = "printed"
        elif len_bubbles == 0 and voter.voted:
          voter_status = "tallied"
        else:
          raise HTTPException(status_code=400, detail="Corrupted voter database entry.")
      elif len_bubbles > 0 or voter.voted:
        raise HTTPException(status_code=400, detail="Corrupted voter database entry.")
      
      voter_response = {
        "precinct": voter.precinct,
        "voter_status": voter_status,
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
     "precinct": voter_response["precinct"],
     "voter_status": voter_response["voter_status"],
  } 

  # Temporary dummy data
  # response = DUMMY_DATA["miguel"]
  # response = DUMMY_DATA["dale"]
  # response = DUMMY_DATA["lian"]
  # response = DUMMY_DATA["yenyen"]

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
  try:
    ballot_data = printing.get_ballot_data(db=db, province=province, city=city)
    pdf_content = printing.build_ballot(ballot_data=ballot_data, uin=uin, db=db)

    # Get voter for later
    voter = db.exec(select(orm.Voter).where(orm.Voter.uin == uin)).first()
    if voter is None:
      raise HTTPException(status_code=404, detail="Invalid voter")
  
  except Exception:
    # Display error on PrecinctOfficer's screen
    return {"status": "failed"}

  # Print before modifying anything to voter data
  result = subprocess.run([
    "lp", "-h", f"localhost:{VM_PORT}", "-d", PRINTER
  ], input=pdf_content, capture_output=True, timeout=30)
  if result.returncode == 0:
    print("Ballot sent to printer successfully.")
  
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

class TallyRequest(BaseModel):
  uin: str
  candidate_ids: list[int]

# This API is used to add a voter's votes into the tally count.
# This will also delete the voter's entries in the bubble_coordinates table.
@app.post("/tally")
async def tally(request: TallyRequest, db: Session = Depends(db_init)):
    
  # Raise an error if voter has already voted.
  voter: orm.Voter = db.exec(
    select(orm.Voter)
    .where(orm.Voter.uin == request.uin)
  ).first()
  if not voter:
    raise HTTPException(
      status_code=400,
      detail="UIN does not correspond to a registered voter."
    )
  if voter.voted:
    raise HTTPException(
      status_code=400,
      detail="Voter has already voted."
    )

  # Make sure votes per position do not exceed position.max_votes.
  # If exceeding, do not incremement tally for that position.
  candidates: list[orm.Candidate] = db.exec(
    select(orm.Candidate)
    .where(orm.Candidate.candidate_id.in_(request.candidate_ids))
  ).all()
  position_candidates: dict[int, list[int]]= defaultdict(list) # position_id -> [candidate_id]
  for c in candidates:
    position_candidates[c.position_id].append(c.candidate_id)
  positions: list[orm.Position] = db.exec(
    select(orm.Position)
  ).all()
  position_map: dict[int, orm.Position] = {p.position_id: p for p in positions}
  valid_candidate_ids: list[int] = []
  invalid_positions: list[str] = []
  for pid, cids in position_candidates.items():
    position = position_map[pid]
    if len(cids) <= position.max_votes:
      valid_candidate_ids.extend(cids)
    else:
      invalid_positions.append(position.position_name)
  db.exec(
    update(orm.Tally)
    .where(orm.Tally.candidate_id.in_(valid_candidate_ids))
    .values(votecount=orm.Tally.votecount+1)
  )

  # Delete bubble_coordinates entries of voter
  db.exec(
    delete(orm.Bubble_Coordinate)
    .where(orm.Bubble_Coordinate.uin == request.uin)
  )

  # Mark voter as voted.
  db.exec(
    update(orm.Voter)
    .where(orm.Voter.uin == request.uin)
    .values(voted=True)
  )
  
  db.commit()
  
  if invalid_positions:
    return {"status": f"Too many votes on: {', '.join(invalid_positions)}. Incremented tally for proper votes."}
  else:
    return {"status": "Added all votes to the tally."}
    

class Component(str, Enum):
  PHONE = "phone"
  PC = "pc"
class MessageType(str, Enum):
  UIN = "uin"
  IMAGE = "image"
  CANDIDATES = "candidates display"
  ACK = "ack"
  ERROR = "error"
class CandidateDisplay(BaseModel):
  candidate_id: int
  first_name: str
  middle_name: Optional[str]
  last_name: str
class Message(BaseModel):
  type: MessageType
  payload: Any

# This WebSocket is to be used by PrecinctOfficer's Phone and PC. 
# Phone sends scanned ballot image bytes to server. Then server processes it to get list of voted candidates.
# Server then sends that list to the PrecinctOfficer's PC. 
devices: Dict[str, Dict[Component, WebSocket]] = {} # device_id -> {Component -> WebSocket}
device_to_voter: Dict[str, str] = {} # device_id -> voter uin
@app.websocket("/scan-ballot/{device_id}/{component}")
async def scan_ballot(websocket: WebSocket, device_id: str, component: Component, db: Session = Depends(db_init)):
  await websocket.accept()

  if device_id not in devices:
    devices[device_id] = {}
  devices[device_id][component] = websocket

  try:
    while True:
      raw = await websocket.receive_json()
      msg = Message(**raw)
      
      # PrecinctOfficer PC sends voter UIN to server. Server associates it to device_id 
      if component == Component.PC:
        if msg.type == MessageType.UIN:
          uin = msg.payload
          device_to_voter[device_id] = uin

          await websocket.send_json(Message(
            type=MessageType.ACK,
            payload=f"PrecinctOfficer PC {device_id} connected to server."
          ).model_dump())

      # PrecinctOfficer Phone sends ballot img bytes to server.
      # Server processes img via OMR, with respect to voter's ballot template
      # Server sends voted candidates list to corresponding PC      
      elif component == Component.PHONE:
        if msg.type == MessageType.IMAGE:
          
          # Make sure that corresponding PrecinctOfficer PC has connected first.
          if device_id not in devices or Component.PC not in devices[device_id] or device_id not in device_to_voter:
            await websocket.send_json(Message(
              type=MessageType.ERROR,
              payload="PrecinctOfficer PC {device_id} not yet connected to server. Please scan again once it is connected."
            ).model_dump())
            continue
          
          img_bytestring: str = msg.payload
          uin = device_to_voter[device_id]
          ballot_template: list[BubbleCoordinate] = printing.get_ballot_template(uin, db)
          omr_input: OMRInputData = OMRInputData(coords_json=ballot_template, scan_bytes=img_bytestring)
          voted_candidates_ids, _ = check_page(omr_input)

          voted_candidates = db.exec(
            select(orm.Candidate)
            .where(col(orm.Candidate.candidate_id).in_(voted_candidates_ids))
          ).all()

          def parse_voted_candidate(candidate: orm.Candidate):
            return CandidateDisplay(candidate_id=candidate.candidate_id, first_name=candidate.first_name, middle_name=candidate.middle_name, last_name=candidate.last_name)

          voted_candidates_list = list(map(parse_voted_candidate, voted_candidates))

          pc_websocket = devices[device_id][Component.PC]
          await pc_websocket.send_json(Message(
            type=MessageType.CANDIDATES,
            payload=[voted_candidate.model_dump_json() for voted_candidate in voted_candidates_list]
          ).model_dump())

  except WebSocketDisconnect:
    if device_id in devices and component in devices[device_id]:
      del devices[device_id][component]
    if device_id in devices and not devices[device_id]:
      devices.pop(device_id, None)
      device_to_voter.pop(device_id, None)


# This HTTP GET endpoint could be called by the tally webpage.
# Essentially, given optional province and city, it returns information regarding the corresponding candidates' votecount. Refer to implementation for how candidates are filtered.
@app.get("/get-tally")
async def get_tally(province: str|None = None, city: str|None = None, db: Session = Depends(db_init)):

  # Validate province
  if province is not None:
    province_obj: orm.Province = db.exec(
      select(orm.Province).
      where(orm.Province.province_name == province)
    ).first()
    if not province_obj:
      raise HTTPException(
        status_code=404,
        detail=f"Province '{province}' not found."
      )
  
  # Validate city
  if city is not None:
    city_obj: orm.City = db.exec(
      select(orm.City)
      .where(orm.City.city_name == city)
    ).first()
    if not city_obj:
      raise HTTPException(
        status_code=404,
        detail=f"City '{city}' not found."
      )

  # Start from all candidates
  sqlquery = (
    select(
      orm.Candidate.candidate_id,
      orm.Candidate.first_name,
      orm.Candidate.middle_name,
      orm.Candidate.last_name,
      orm.Candidate.party,
      orm.Candidate.position_id,
      orm.Position.position_name,
      orm.Scope.scope_id,
      orm.Scope.scope_name,
      orm.Candidate.province_id,
      orm.Province.province_name,
      orm.Candidate.city_id,
      orm.City.city_name,
      orm.Tally.votecount
    )
    .join(orm.Position, orm.Candidate.position_id == orm.Position.position_id)
    .join(orm.Scope, orm.Position.scope_id == orm.Scope.scope_id)
    .join(orm.Tally, orm.Candidate.candidate_id == orm.Tally.candidate_id)
    .join(orm.Province, orm.Candidate.province_id == orm.Province.province_id, isouter=True)
    .join(orm.City, orm.Candidate.city_id == orm.City.city_id, isouter=True)
  )

  # If province and city are None, return tally for national scope only
  if province is None and city is None:
    sqlquery = sqlquery.where(orm.Scope.scope_id == 1)
  
  # If province is provided, but city is None, return tally for that province only.
  elif province is not None and city is None:
    sqlquery = sqlquery.where(
      and_(
        orm.Scope.scope_id == 2,
        orm.Province.province_name == province
      )
    )

  # If province is None, but city is provided, return tally for that city only
  elif province is None and city is not None:
    sqlquery = sqlquery.where(
      and_(
        orm.Scope.scope_id == 3,
        orm.City.city_name == city
      )
    )
  
  # If province and city are provided, return tallies for national scope, that province's scope, and that city's scope
  else:
    sqlquery = sqlquery.where(
      or_(
        orm.Scope.scope_id == 1,
        and_(
          orm.Scope.scope_id == 2,
          orm.Province.province_name == province
        ),
        and_(
          orm.Scope.scope_id == 3,
          orm.City.city_name == city
        )
      )
    )
  
  # For convenience, sort by scope_id and then by votecount.
  sqlquery = sqlquery.order_by(
    orm.Candidate.position_id, 
    orm.Tally.votecount.desc()
  )

  results = db.exec(sqlquery).mappings().all()
  return results