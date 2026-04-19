from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Dict
from kyc_auth import kyc_auth

app = FastAPI()

# device_id -> WebSocket of precinctOfficer.
precinct_officer: Dict[str, WebSocket] = {}

class ScanRequest(BaseModel):
  device_id: str
  qr: dict


# /scan is called by ESP8266 to send decoded QR to server.
# Then, kyc_auth the decoded QR data
# Then, send kyc_auth response to corresponding precinct_officer 
@app.post("/scan")
async def scan(payload: ScanRequest):
  device_id = payload.device_id

  # MOSIP Response from kyc_auth.py
  uin: str = payload.qr.get("uin")
  dob: str = payload.qr.get("dob")
  try:
    mosip_response = kyc_auth(uin, dob)
  except Exception as e:
    mosip_response = {
      "error": str(e)
    }

  if device_id in precinct_officer:
    precinct_officer[device_id].send_json(mosip_response)

  return {
    "status": "sent", 
    "device_id": device_id, 
    "mosip_reponse": mosip_response
  }
  