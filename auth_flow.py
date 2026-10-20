#!/usr/bin/env python3
import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send"
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRETS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")
OUTPUT_TOKEN_FILE = os.path.join(SCRIPT_DIR, "drive_token.json")
ADC_DIR = os.path.expanduser("~/.config/gcloud")
ADC_FILE = os.path.join(ADC_DIR, "application_default_credentials.json")

def main():
    print("=" * 60)
    print("🔑 Artefact EOM OAuth Authorization Flow")
    print("=" * 60)
    print(f"Reading Client Secrets: {CLIENT_SECRETS_FILE}")
    print("Requested Scopes:")
    for s in SCOPES:
        print(f" - {s}")
    print("=" * 60)

    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES
    )

    print("\n👉 A browser window will open automatically for Google Sign-In.")
    print("Please select your Artefact account (e.g. ayrton.andre@artefact.com) and grant permissions.\n")

    # Run local server to catch the authorization redirect
    creds = flow.run_local_server(
        port=8085,
        prompt="consent",
        access_type="offline",
        open_browser=True
    )

    # 1. Save to project drive_token.json
    with open(OUTPUT_TOKEN_FILE, "w") as token_out:
        token_out.write(creds.to_json())
    print(f"✅ Saved full credentials to: {OUTPUT_TOKEN_FILE}")

    # 2. Save to standard Google Cloud ADC location
    os.makedirs(ADC_DIR, exist_ok=True)
    with open(ADC_FILE, "w") as adc_out:
        adc_out.write(creds.to_json())
    print(f"✅ Saved Google Cloud Application Default Credentials to: {ADC_FILE}")

    print("\n🎉 Authorization complete! Both Google Cloud Agent Platform and Workspace APIs are ready.")

if __name__ == "__main__":
    main()
