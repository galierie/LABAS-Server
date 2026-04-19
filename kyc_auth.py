from mosip_auth_sdk.models import DemographicsModel
from mosip_auth_sdk import MOSIPAuthenticator
from dynaconf import Dynaconf
import numpy as np
import base64
import cv2

config = Dynaconf(settings_files=["./certs/config.toml"], environments=False)
authenticator = MOSIPAuthenticator(config=config)

# kyc auth
demographics_data = DemographicsModel(dob="2023/02/08")
response = authenticator.kyc(
    individual_id="6874180926",
    individual_id_type="UIN",
    demographic_data=demographics_data,
    consent=True,
)
response_body = response.json()
decrypted_response = authenticator.decrypt_response(response_body)
face_bytes = base64.b64decode(decrypted_response.pop("photo"))

# shows demographic data
print(f"DECRYPTED RESPONSE: {decrypted_response}")

# attempt to decode image from face_bytes
img = None
offsets_to_try = [i for i in range(70, 85)]
for offset in offsets_to_try:
    face_as_np = np.frombuffer(face_bytes[offset:], dtype=np.uint8)
    img = cv2.imdecode(face_as_np, cv2.IMREAD_COLOR)
    if img is not None:
        print(f"Found valid image at offset {offset}")
        break

if img is None:
    print("ERROR: Could not decode image")
    exit(1)

# show image in window and save to file when 's' is pressed
# cv2.imshow("test", img)
# k = cv2.waitKey(0)

# if k == ord("s"):
#     cv2.imwrite("./face.jpg", img)
#     exit()


# For headless, just save the image for now.
cv2.imwrite("./face.jpg", img)
print("Image saved as face.jpg")
