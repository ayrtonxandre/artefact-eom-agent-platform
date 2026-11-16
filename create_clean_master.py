import os
import sys
import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eom_agent.workspace_service import get_drive_service, get_slides_service

drive = get_drive_service()
slides_svc = get_slides_service()

# Copy 1kUt0y78bLJ9WGR99I9bzJZTIGcAYbO8sbsgINpUiynU
new_pres = drive.files().copy(
    fileId="1kUt0y78bLJ9WGR99I9bzJZTIGcAYbO8sbsgINpUiynU",
    body={"name": "[Official Master Template] Artefact EOM One-Pager Deck 2025"},
    supportsAllDrives=True,
    fields="id, webViewLink"
).execute()

new_id = new_pres["id"]
print("Created new presentation ID:", new_id)

# Fetch slides to find non-slide-4 IDs
pres = slides_svc.presentations().get(presentationId=new_id).execute()
slides = pres.get("slides", [])
print("Original total slides:", len(slides))

del_reqs = []
for i, s in enumerate(slides):
    if i != 3: # Keep index 3 (Slide 4)
        del_reqs.append({"deleteObject": {"objectId": s["objectId"]}})

if del_reqs:
    slides_svc.presentations().batchUpdate(presentationId=new_id, body={"requests": del_reqs}).execute()

# Verify remaining slides
pres_after = slides_svc.presentations().get(presentationId=new_id).execute()
rem_slides = pres_after.get("slides", [])
print("Remaining slides count:", len(rem_slides))
rem_id = rem_slides[0]["objectId"]
print("Remaining slide ID:", rem_id)
print("New template URL:", new_pres.get("webViewLink"))
