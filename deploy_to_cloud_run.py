#!/usr/bin/env python3
"""
Automated Cloud Run Deployment Script for Artefact EOM Platform.
Builds the container image via Cloud Build and deploys revision to Cloud Run
using the user's authenticated Google credentials (ADC).
"""
import os
import io
import sys
import json
import time
import zipfile
import base64
import requests

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

PROJECT_ID = "privategpt-437907"
REGION = "europe-west1"
SERVICE_NAME = "eom-workspace-service"
BUCKET_NAME = "run-sources-privategpt-437907-europe-west1"
IMAGE_TAG = f"europe-west1-docker.pkg.dev/{PROJECT_ID}/cloud-run-source-deploy/{SERVICE_NAME}:latest"

WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
SERVICE_DIR = os.path.join(WORKSPACE_DIR, "service")
TOKEN_FILE = os.path.join(WORKSPACE_DIR, "drive_token.json")

def get_auth_headers():
    adc_path = os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
    with open(adc_path) as f:
        info = json.load(f)
    creds = Credentials.from_authorized_user_info(info, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    return {"Authorization": f"Bearer {creds.token}"}

def create_source_zip() -> bytes:
    print("📦 Creating source zip archive of service and eom_agent...")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add service files
        for fname in ["Dockerfile", "requirements.txt", "main.py"]:
            fpath = os.path.join(SERVICE_DIR, fname)
            if os.path.exists(fpath):
                zf.write(fpath, arcname=fname)
        
        # Add eom_agent module
        agent_dir = os.path.join(WORKSPACE_DIR, "eom_agent")
        for root, _, files in os.walk(agent_dir):
            if "__pycache__" in root:
                continue
            for file in files:
                if file.endswith((".py", ".json", ".txt")):
                    full_p = os.path.join(root, file)
                    rel_p = os.path.relpath(full_p, WORKSPACE_DIR)
                    zf.write(full_p, arcname=rel_p)
    buffer.seek(0)
    zip_bytes = buffer.getvalue()
    print(f"✅ Source zip created ({len(zip_bytes)} bytes)")
    return zip_bytes

def upload_to_gcs(headers: dict, zip_bytes: bytes) -> str:
    timestamp = int(time.time())
    object_name = f"services/{SERVICE_NAME}/{timestamp}.zip"
    upload_url = f"https://storage.googleapis.com/upload/storage/v1/b/{BUCKET_NAME}/o?uploadType=media&name={object_name}"
    
    print(f"☁️  Uploading source archive to gs://{BUCKET_NAME}/{object_name}...")
    upload_headers = dict(headers)
    upload_headers["Content-Type"] = "application/zip"
    resp = requests.post(upload_url, headers=upload_headers, data=zip_bytes)
    resp.raise_for_status()
    print("✅ Upload completed successfully.")
    return object_name

def trigger_cloud_build(headers: dict, object_name: str) -> str:
    print("🔨 Submitting Cloud Build job to build container image...")
    build_payload = {
        "source": {
            "storageSource": {
                "bucket": BUCKET_NAME,
                "object": object_name
            }
        },
        "steps": [
            {
                "name": "gcr.io/cloud-builders/docker",
                "args": ["build", "-t", IMAGE_TAG, "."]
            },
            {
                "name": "gcr.io/cloud-builders/docker",
                "args": ["push", IMAGE_TAG]
            }
        ],
        "images": [IMAGE_TAG]
    }
    
    resp = requests.post(
        f"https://cloudbuild.googleapis.com/v1/projects/{PROJECT_ID}/builds",
        headers=headers,
        json=build_payload
    )
    resp.raise_for_status()
    build_data = resp.json()
    build_id = build_data["metadata"]["build"]["id"]
    print(f"🚀 Cloud Build started (Build ID: {build_id})")
    return build_id

def wait_for_build(headers: dict, build_id: str):
    print("⏳ Waiting for Cloud Build to complete...")
    while True:
        resp = requests.get(
            f"https://cloudbuild.googleapis.com/v1/projects/{PROJECT_ID}/builds/{build_id}",
            headers=headers
        )
        resp.raise_for_status()
        status = resp.json().get("status")
        print(f"   Build status: {status}")
        if status in ("SUCCESS", "FAILURE", "INTERNAL_ERROR", "TIMEOUT", "CANCELLED"):
            if status != "SUCCESS":
                raise RuntimeError(f"Cloud Build failed with status: {status}")
            print("✅ Container image built and pushed successfully!")
            break
        time.sleep(10)

def deploy_to_cloud_run(headers: dict):
    print("🚀 Updating Cloud Run service with new revision...")
    
    # Read token for DRIVE_TOKEN_JSON env var
    env_vars = [
        {"name": "GCP_PROJECT", "value": PROJECT_ID}
    ]
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as tf:
            b64_tok = base64.b64encode(tf.read()).decode("utf-8")
        env_vars.append({"name": "DRIVE_TOKEN_JSON", "value": b64_tok})

    svc_url = f"https://europe-west1-run.googleapis.com/apis/serving.knative.dev/v1/namespaces/{PROJECT_ID}/services/{SERVICE_NAME}"
    resp = requests.get(svc_url, headers=headers)
    resp.raise_for_status()
    service_spec = resp.json()

    # Update template container image and env vars
    template = service_spec.setdefault("spec", {}).setdefault("template", {})
    template.setdefault("spec", {})["serviceAccountName"] = "eom-chat-ap@privategpt-437907.iam.gserviceaccount.com"
    containers = template.setdefault("spec", {}).setdefault("containers", [{}])
    containers[0]["image"] = IMAGE_TAG
    containers[0]["env"] = env_vars

    # Force a new revision by stamping metadata annotations
    meta = template.setdefault("metadata", {})
    annotations = meta.setdefault("annotations", {})
    annotations["deploy-timestamp"] = str(int(time.time()))

    # Ensure 100% traffic to latest revision
    service_spec.setdefault("spec", {})["traffic"] = [{"percent": 100, "latestRevision": True}]

    put_resp = requests.put(svc_url, headers=headers, json=service_spec)
    put_resp.raise_for_status()
    print("✅ Cloud Run revision update submitted successfully!")
    print(f"🔗 Endpoint URL: {put_resp.json().get('status', {}).get('url')}")

def wait_for_service_ready(headers: dict):
    print("⏳ Waiting for Cloud Run revision to become healthy and ready...")
    svc_url = f"https://europe-west1-run.googleapis.com/apis/serving.knative.dev/v1/namespaces/{PROJECT_ID}/services/{SERVICE_NAME}"
    for _ in range(36):
        time.sleep(10)
        resp = requests.get(svc_url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            latest_created = data.get("status", {}).get("latestCreatedRevisionName")
            latest_ready = data.get("status", {}).get("latestReadyRevisionName")
            conditions = {c.get("type"): c.get("status") for c in data.get("status", {}).get("conditions", [])}
            print(f"   Latest Created: {latest_created} | Latest Ready: {latest_ready} | Conditions: {conditions}")
            if latest_ready == latest_created and conditions.get("Ready") == "True":
                print(f"✅ Cloud Run Service is READY on revision {latest_ready}!")
                return
            if conditions.get("Ready") == "False":
                print(f"⚠️ Service reported Ready: False! Check revision logs.")
                break
    print("⚠️ Timeout or failed waiting for revision readiness.")

def verify_endpoints():
    print("🔍 Verifying deployed endpoints...")
    try:
        url = "https://eom-workspace-service-6vcfc2gc7q-ew.a.run.app/openapi.json"
        resp = requests.get(url, headers={"User-Agent": "EOMDeploy/1.0"}, timeout=10)
        if resp.status_code == 200:
            paths = list(resp.json().get("paths", {}).keys())
            print(f"✅ Verified live OpenAPI paths ({len(paths)} routes):")
            for p in paths:
                print(f"   - {p}")
        else:
            print(f"⚠️ HTTP {resp.status_code} fetching openapi.json: {resp.text[:200]}")
    except Exception as e:
        print(f"⚠️ Could not reach endpoint: {e}")

def main():
    print("=" * 70)
    print("🚀 ARTEFACT EOM CLOUD RUN REDEPLOYMENT")
    print("=" * 70)
    headers = get_auth_headers()
    zip_bytes = create_source_zip()
    obj_name = upload_to_gcs(headers, zip_bytes)
    build_id = trigger_cloud_build(headers, obj_name)
    wait_for_build(headers, build_id)
    deploy_to_cloud_run(headers)
    wait_for_service_ready(headers)
    verify_endpoints()
    print("\n🎉 Redeployment complete!")

if __name__ == "__main__":
    main()
