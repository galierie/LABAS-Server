from mosip_auth_sdk.models import DemographicsModel
from mosip_auth_sdk import MOSIPAuthenticator
from dynaconf import Dynaconf
from typing import Dict
from dotenv import load_dotenv
import os
import numpy as np
import base64
import cv2
import requests

# MUST HAVE EXACT PATH OF settings_files
load_dotenv()
CONFIG_TOML = os.getenv("CONFIG_TOML")
config = Dynaconf(settings_files=[CONFIG_TOML], environments=False)
authenticator = MOSIPAuthenticator(config=config)
MOSIP_MODE = os.getenv("MOSIP_MODE")

# Given UIN and DOB from decoded QR
# Authenticate the QR code's data
# Return demographic data and ID' photo
def kyc_auth(uin: str, dob: str) -> Dict:
    assert MOSIP_MODE == "mock" or MOSIP_MODE == "sdk"
    
    if MOSIP_MODE == "mock":
        return _kyc_auth_mock(uin, dob)
    else:
        return _kyc_auth_sdk(uin, dob)

def _kyc_auth_mock(uin: str, dob: str) -> Dict:
    mock_server_url = "https://cs145-iot-cup-1745973870.ap-southeast-1.elb.amazonaws.com/"
    
    try:
        response =  requests.post(
            f"{mock_server_url}/api/v1/auth/kyc",
            json={
                "individual_id": uin,
                "consent": True,
                "dob": dob
            },
            verify=False
        )
        response_body = response.json()
        decrypted_response = response_body["response"]
        face_bytes = base64.b64decode(decrypted_response.pop("photo"))
    except Exception as e:
        print(e)
        raise Exception(e)
    
    # Attempt to decode image from face_bytes
    img = None
    offsets_to_try = [i for i in range(70, 85)]
    for offset in offsets_to_try:
        face_as_np = np.frombuffer(face_bytes[offset:], dtype=np.uint8)
        img = cv2.imdecode(face_as_np, cv2.IMREAD_COLOR)
        if img is not None:
            break
    if img is None:
        raise Exception("Could not decode image")

    # Convert img->jpeg->base64
    _, buffer = cv2.imencode(".jpg", img)
    img_base64 = base64.b64encode(buffer).decode("utf-8")

    return {
        "uin": uin,
        "demographics": decrypted_response,
        "photo": img_base64
    }   

def _kyc_auth_sdk(uin: str, dob: str) -> Dict:
    # User-1 UIN: 6874180926
    # User-1 dob: 2023/02/08

    # Retrieve demographic data via kyc
    demographics_data = DemographicsModel(dob=dob)
    response = authenticator.kyc(
        individual_id=uin,
        individual_id_type="UIN",
        demographic_data=demographics_data,
        consent=True,
    )
    try:
        response_body = response.json()
        decrypted_response = authenticator.decrypt_response(response_body)
        face_bytes = base64.b64decode(decrypted_response.pop("photo"))
    except Exception as e:
        raise Exception("MOSIP Authentication Failed.")

    # Attempt to decode image from face_bytes
    img = None
    offsets_to_try = [i for i in range(70, 85)]
    for offset in offsets_to_try:
        face_as_np = np.frombuffer(face_bytes[offset:], dtype=np.uint8)
        img = cv2.imdecode(face_as_np, cv2.IMREAD_COLOR)
        if img is not None:
            break
    if img is None:
        raise Exception("Could not decode image")

    # Convert img->jpeg->base64
    _, buffer = cv2.imencode(".jpg", img)
    img_base64 = base64.b64encode(buffer).decode("utf-8")

    return {
        "uin": uin,
        "demographics": decrypted_response,
        "photo": img_base64
    }   