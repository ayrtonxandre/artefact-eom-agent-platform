import os
import re
import json
import base64
from datetime import datetime
from email.mime.text import MIMEText
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import google.auth
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# =============================================================================
# AUTHENTICATION HELPER & CONSTANTS
# =============================================================================

CENTRAL_TRACKER_NAME = "[Artefact EOM] Central Pipeline Status Tracker"
CENTRAL_TRACKER_TAB = "Pipeline Status Log"
DEFAULT_TRACKER_ID = "1IDMXRrgiONxaxqB1N-ahRMoiHx4tqfB9vxhSxyhnH7s"
TRACKER_HEADERS = [
    "Mission Name",
    "Client",
    "Lead Email",
    "Status",
    "One-Pager Deck",
    "Audit Sheet",
    "Drive Folder",
    "Confidentiality Risk",
    "Last Updated",
    "Notes"
]

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send"
]

def get_credentials():
    """
    Resolves Google Credentials:
    1. Checks DRIVE_TOKEN_JSON environment variable (base64 or raw JSON string).
    2. Checks DRIVE_TOKEN_PATH or local drive_token.json files.
    3. Falls back to Application Default Credentials (ADC) for Cloud Run / Cloud Functions.
    """
    # 1. Check raw or base64 JSON in environment variable
    raw_token = os.environ.get("DRIVE_TOKEN_JSON")
    if raw_token:
        try:
            raw_str = raw_token.strip()
            if raw_str.startswith("{"):
                info = json.loads(raw_str)
            else:
                info = json.loads(base64.b64decode(raw_str).decode("utf-8"))
            return Credentials.from_authorized_user_info(info, SCOPES)
        except Exception as e:
            print(f"[Auth] Could not load from DRIVE_TOKEN_JSON: {e}")

    # 2. Check local file paths
    token_candidates = [
        os.environ.get("DRIVE_TOKEN_PATH"),
        os.path.join(os.path.dirname(__file__), "drive_token.json"),
        os.path.join(os.path.dirname(__file__), "..", "drive_token.json"),
        "/Users/ayrtonandre/eom_agent_platform/drive_token.json",
        os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
    ]

    for cand in token_candidates:
        if cand and os.path.exists(cand):
            try:
                return Credentials.from_authorized_user_file(cand, SCOPES)
            except Exception as e:
                print(f"[Auth] Could not load authorized user file from {cand}: {e}")

    # 3. Fallback to Google Application Default Credentials (ADC)
    creds, _ = google.auth.default(scopes=SCOPES)
    return creds

def get_drive_service(creds=None):
    return build("drive", "v3", credentials=creds or get_credentials())

def get_slides_service(creds=None):
    return build("slides", "v1", credentials=creds or get_credentials())

def get_sheets_service(creds=None):
    return build("sheets", "v4", credentials=creds or get_credentials())

def get_gmail_service(creds=None):
    return build("gmail", "v1", credentials=creds or get_credentials())

def parse_folder_id(raw_id_or_url: str) -> str:
    """Extracts 28-33 char Google Drive folder ID from full URL or returns raw ID."""
    match = re.search(r"folders/([a-zA-Z0-9_-]+)", str(raw_id_or_url))
    if match:
        return match.group(1)
    return str(raw_id_or_url).strip()

def format_card_text(val: Any) -> str:
    """Converts arrays, dicts, or strings into clean, formatted text bullets."""
    if not val:
        return "N/A"
    if isinstance(val, list):
        return "\n".join([f"• {str(item).strip()}" for item in val])
    if isinstance(val, dict):
        return "\n".join([f"• {k}: {v}" for k, v in val.items()])
    return str(val).strip()

def get_or_create_central_tracker_sheet(creds=None) -> str:
    """
    Returns the spreadsheet ID of the Central Pipeline Status Tracker.
    If the spreadsheet does not exist yet, creates and formats it automatically.
    """
    env_id = os.environ.get("CENTRAL_TRACKER_ID")
    if env_id:
        return env_id
    if DEFAULT_TRACKER_ID:
        return DEFAULT_TRACKER_ID

    drive_svc = get_drive_service(creds)
    sheets_svc = get_sheets_service(creds)

    res = drive_svc.files().list(
        q=f"name = '{CENTRAL_TRACKER_NAME}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields="files(id, name)"
    ).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    # Create new central tracker spreadsheet
    ss_body = {
        "properties": {"title": CENTRAL_TRACKER_NAME},
        "sheets": [{
            "properties": {
                "sheetId": 0,
                "title": CENTRAL_TRACKER_TAB,
                "gridProperties": {"frozenRowCount": 1}
            }
        }]
    }
    ss = sheets_svc.spreadsheets().create(body=ss_body, fields="spreadsheetId").execute()
    new_id = ss["spreadsheetId"]

    # Write Header row
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=new_id,
        range=f"'{CENTRAL_TRACKER_TAB}'!A1:J1",
        valueInputOption="USER_ENTERED",
        body={"values": [TRACKER_HEADERS]}
    ).execute()

    # Apply corporate formatting (Artefact Dark Navy #0F172A)
    format_reqs = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": 0,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(TRACKER_HEADERS)
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.06, "green": 0.09, "blue": 0.16},
                        "textFormat": {"bold": True, "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}, "fontSize": 10}
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)"
            }
        },
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": 0,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": len(TRACKER_HEADERS)
                }
            }
        }
    ]
    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=new_id,
        body={"requests": format_reqs}
    ).execute()

    return new_id


def handle_log_pipeline_status(
    mission_name: str,
    status: str,
    client: Optional[str] = None,
    lead_email: Optional[str] = None,
    deck_url: Optional[str] = None,
    audit_url: Optional[str] = None,
    folder_url: Optional[str] = None,
    risk: Optional[str] = None,
    notes: Optional[str] = None,
    tracker_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Step 7 in Artefact Target EOM Process: Maintains the central status log.
    Upserts the pipeline milestone into the Central Pipeline Status Tracker spreadsheet.
    Prevents duplicate rows by updating existing mission entries in place.
    """
    creds = get_credentials()
    sheets_svc = get_sheets_service(creds)
    target_tracker_id = tracker_id or get_or_create_central_tracker_sheet(creds)
    tab_name = CENTRAL_TRACKER_TAB
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Read existing rows
    try:
        res = sheets_svc.spreadsheets().values().get(
            spreadsheetId=target_tracker_id,
            range=f"'{tab_name}'!A:J"
        ).execute()
        rows = res.get("values", [])
    except Exception as e:
        print(f"[Tracker] Error reading tracker spreadsheet {target_tracker_id}: {e}")
        rows = []

    target_row_idx = None
    existing_row = []
    clean_mission = mission_name.strip().lower()

    for idx, r in enumerate(rows):
        if r and r[0].strip().lower() == clean_mission:
            target_row_idx = idx + 1  # 1-indexed for Sheets API
            existing_row = r
            break

    def get_existing(col_idx: int) -> str:
        if existing_row and len(existing_row) > col_idx:
            return existing_row[col_idx]
        return ""

    # Merge updated fields with existing fields (preserves non-empty data across stages)
    row_values = [
        mission_name,
        client or get_existing(1),
        lead_email or get_existing(2),
        status or get_existing(3),
        deck_url or get_existing(4),
        audit_url or get_existing(5),
        folder_url or get_existing(6),
        risk or get_existing(7),
        now_str,
        notes if notes is not None else get_existing(9)
    ]

    try:
        if target_row_idx:
            sheets_svc.spreadsheets().values().update(
                spreadsheetId=target_tracker_id,
                range=f"'{tab_name}'!A{target_row_idx}:J{target_row_idx}",
                valueInputOption="USER_ENTERED",
                body={"values": [row_values]}
            ).execute()
            action = f"UPDATED row {target_row_idx}"
        else:
            sheets_svc.spreadsheets().values().append(
                spreadsheetId=target_tracker_id,
                range=f"'{tab_name}'!A:J",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [row_values]}
            ).execute()
            action = "APPENDED new row"

        return {
            "status": "SUCCESS",
            "action": action,
            "missionName": mission_name,
            "pipelineStatus": status,
            "trackerId": target_tracker_id,
            "updatedAt": now_str
        }
    except Exception as e:
        print(f"[Tracker] Failed to update central status tracker: {e}")
        return {
            "status": "FAILED",
            "error": str(e),
            "missionName": mission_name,
            "pipelineStatus": status
        }

# =============================================================================
# CORE BUSINESS LOGIC HANDLERS
# =============================================================================

def handle_extract_documents(folder_raw: str) -> Dict[str, Any]:
    folder_id = parse_folder_id(folder_raw)
    drive_svc = get_drive_service()

    # 1. Fetch Folder Metadata
    folder_meta = drive_svc.files().get(
        fileId=folder_id,
        fields="id, name",
        supportsAllDrives=True
    ).execute()
    mission_name = folder_meta.get("name", "Mission").replace("TEST_", "").strip()

    # 2. List Files in Folder
    query = f"'{folder_id}' in parents and trashed = false"
    res = drive_svc.files().list(
        q=query,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields="files(id, name, mimeType, modifiedTime, size)"
    ).execute()

    raw_files = res.get("files", [])
    extracted_files = []

    for f in raw_files:
        fname = f["name"]
        fid = f["id"]
        mime = f["mimeType"]

        # Exclude existing generated outputs to avoid self-ingestion loops
        if fname.startswith("[One-Pager]") or fname.startswith("[Checklist & Audit]"):
            continue

        content = ""
        try:
            if mime == "application/vnd.google-apps.document":
                data = drive_svc.files().export(fileId=fid, mimeType="text/plain").execute()
                content = data.decode("utf-8", errors="ignore")
            elif mime == "application/vnd.google-apps.presentation":
                data = drive_svc.files().export(fileId=fid, mimeType="text/plain").execute()
                content = data.decode("utf-8", errors="ignore")
            elif mime.startswith("text/") or fname.endswith((".txt", ".md", ".csv", ".json", ".py", ".sql")):
                data = drive_svc.files().get_media(fileId=fid).execute()
                content = data.decode("utf-8", errors="ignore")
            else:
                content = f"Binary/Non-text file: {fname} ({mime})"
        except Exception as read_err:
            content = f"[Warning: Could not extract full text: {read_err}]"

        # Safeguard character cap per file
        truncated_content = content[:10000]
        extracted_files.append({
            "id": fid,
            "name": fname,
            "mimeType": mime,
            "content": truncated_content
        })

    aggregated_context = "\n\n".join(
        [f"--- FILE: {item['name']} ---\n{item['content']}" for item in extracted_files]
    )

    folder_url = f"https://drive.google.com/drive/folders/{folder_id}"

    # Step 7: Record milestone into Central Status Tracker
    try:
        handle_log_pipeline_status(
            mission_name=mission_name,
            status="DOCS_EXTRACTED",
            folder_url=folder_url,
            notes=f"Extracted {len(extracted_files)} files from Drive folder"
        )
    except Exception as e:
        print(f"[Tracker] Step 7 auto-log warning in extract_documents: {e}")

    return {
        "folderId": folder_id,
        "missionName": mission_name,
        "filesCount": len(extracted_files),
        "files": extracted_files,
        "aggregatedContext": aggregated_context
    }


def handle_generate_slide(folder_raw: str, mission_name: str, card: Any, template_id: Optional[str] = None) -> Dict[str, Any]:
    folder_id = parse_folder_id(folder_raw)
    creds = get_credentials()
    drive_svc = get_drive_service(creds)
    slides_svc = get_slides_service(creds)

    if isinstance(card, str):
        try:
            cleaned = card.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            card = json.loads(cleaned)
        except Exception:
            card = {"context": card}
    elif not isinstance(card, dict):
        card = {}

    template_id = template_id or "197zP6K146fFlNSPDrDuHoUiKS9c0KODiypl_u27XWDQ"
    new_title = f"[One-Pager] {mission_name}"

    # Deduplication: clean up any existing duplicate presentations in target mission folder
    try:
        dup_query = f"'{folder_id}' in parents and name = '{new_title}' and mimeType = 'application/vnd.google-apps.presentation' and trashed = false"
        dup_res = drive_svc.files().list(
            q=dup_query,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            fields="files(id, name)"
        ).execute()
        for existing in dup_res.get("files", []):
            try:
                drive_svc.files().delete(fileId=existing["id"], supportsAllDrives=True).execute()
            except Exception:
                try:
                    drive_svc.files().update(
                        fileId=existing["id"],
                        body={"name": f"[Archive - {datetime.now().strftime('%Y%m%d_%H%M')}] {new_title}"},
                        supportsAllDrives=True
                    ).execute()
                except Exception:
                    pass
    except Exception as dup_err:
        print(f"[Slide Deduplication Warning] Could not check/clean stale presentations: {dup_err}")

    # 1. Copy Master Slide Template to Target Mission Folder
    copy_body = {
        "name": new_title,
        "parents": [folder_id]
    }
    copied_file = drive_svc.files().copy(
        fileId=template_id,
        body=copy_body,
        supportsAllDrives=True,
        fields="id, webViewLink"
    ).execute()

    presentation_id = copied_file["id"]
    presentation_url = copied_file.get("webViewLink", f"https://docs.google.com/presentation/d/{presentation_id}/edit")

    today_str = datetime.now().strftime("%Y-%m-%d")

    context_val = card.get("context") or card.get("Context") or ""
    deliverables_val = card.get("deliverables") or card.get("Deliverables") or ""
    impact_val = card.get("businessImpact") or card.get("business_impact") or card.get("BusinessImpact") or ""
    recs_val = card.get("recommendations") or card.get("Recommendations") or ""
    synthesis_val = card.get("synthesis") or card.get("Synthesis") or context_val

    # 2. Build Slide Replace Requests
    requests = [
        {"replaceAllText": {"replaceText": mission_name, "containsText": {"matchCase": True, "text": "{{MISSION_NAME}}"}}},
        {"replaceAllText": {"replaceText": today_str, "containsText": {"matchCase": True, "text": "{{DATE}}"}}},
        {"replaceAllText": {"replaceText": format_card_text(context_val), "containsText": {"matchCase": True, "text": "{{CONTEXT}}"}}},
        {"replaceAllText": {"replaceText": format_card_text(deliverables_val), "containsText": {"matchCase": True, "text": "{{DELIVERABLES}}"}}},
        {"replaceAllText": {"replaceText": format_card_text(impact_val), "containsText": {"matchCase": True, "text": "{{BUSINESS_IMPACT}}"}}},
        {"replaceAllText": {"replaceText": format_card_text(recs_val), "containsText": {"matchCase": True, "text": "{{RECOMMENDATIONS}}"}}},
        {"replaceAllText": {"replaceText": format_card_text(synthesis_val), "containsText": {"matchCase": True, "text": "{{SYNTHESIS}}"}}}
    ]

    # 3. Batch Update Slide Deck
    slides_svc.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": requests}
    ).execute()

    # Step 7: Record milestone into Central Status Tracker
    try:
        handle_log_pipeline_status(
            mission_name=mission_name,
            status="DECK_GENERATED",
            deck_url=presentation_url,
            notes="Executive one-pager slide deck generated"
        )
    except Exception as e:
        print(f"[Tracker] Step 7 auto-log warning in generate_slide: {e}")

    return {
        "presentationId": presentation_id,
        "presentationUrl": presentation_url,
        "title": new_title
    }


def handle_create_audit_sheet(folder_raw: str, mission_name: str, audit_records: Any) -> Dict[str, Any]:
    folder_id = parse_folder_id(folder_raw)
    creds = get_credentials()
    drive_svc = get_drive_service(creds)
    sheets_svc = get_sheets_service(creds)

    if isinstance(audit_records, str):
        try:
            cleaned = audit_records.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            audit_records = json.loads(cleaned)
        except Exception:
            audit_records = []
    elif not isinstance(audit_records, list):
        audit_records = []

    sheet_title = f"[Checklist & Audit] {mission_name}"
    tab_name = "Knowledge Audit"

    # Deduplication: Check if an audit spreadsheet already exists in the mission folder
    existing_files = []
    try:
        search_query = f"'{folder_id}' in parents and name = '{sheet_title}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
        res = drive_svc.files().list(
            q=search_query,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            fields="files(id, name, webViewLink)"
        ).execute()
        existing_files = res.get("files", [])
    except Exception as search_err:
        print(f"[Audit Sheet Search Warning]: {search_err}")

    if existing_files:
        # Reuse canonical existing spreadsheet
        spreadsheet_id = existing_files[0]["id"]
        spreadsheet_url = existing_files[0].get("webViewLink", f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")

        # Clean up any duplicate spreadsheets created on previous runs
        for extra in existing_files[1:]:
            try:
                drive_svc.files().delete(fileId=extra["id"], supportsAllDrives=True).execute()
            except Exception:
                pass

        # Inspect tabs to locate Knowledge Audit sheetId
        target_sheet_id = 0
        try:
            ss_meta = sheets_svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            sheets_list = ss_meta.get("sheets", [])
            tab_found = False
            for s in sheets_list:
                props = s.get("properties", {})
                if props.get("title") == tab_name:
                    target_sheet_id = props.get("sheetId", 0)
                    tab_found = True
                    break

            if not tab_found and sheets_list:
                target_sheet_id = sheets_list[0].get("properties", {}).get("sheetId", 0)
                sheets_svc.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={"requests": [{
                        "updateSheetProperties": {
                            "properties": {"sheetId": target_sheet_id, "title": tab_name},
                            "fields": "title"
                        }
                    }]}
                ).execute()

            # Clear existing data on the tab to prevent residual stale rows
            sheets_svc.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=f"'{tab_name}'!A:Z"
            ).execute()
        except Exception as inspect_err:
            print(f"[Audit Sheet Reuse Warning]: {inspect_err}")

    else:
        # 1. Create Spreadsheet
        ss_body = {
            "properties": {"title": sheet_title},
            "sheets": [{"properties": {"sheetId": 0, "title": tab_name}}]
        }
        ss = sheets_svc.spreadsheets().create(
            body=ss_body,
            fields="spreadsheetId,spreadsheetUrl,sheets(properties(sheetId,title))"
        ).execute()
        spreadsheet_id = ss["spreadsheetId"]
        spreadsheet_url = ss.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")
        target_sheet_id = ss.get("sheets", [{}])[0].get("properties", {}).get("sheetId", 0)

        # 2. Move Spreadsheet to Target Mission Folder
        drive_svc.files().update(
            fileId=spreadsheet_id,
            addParents=folder_id,
            removeParents="root",
            supportsAllDrives=True,
            fields="id, parents"
        ).execute()

    # 3. Prepare Header & Rows
    values = [["Filename", "Confidentiality Risk", "Suggested Tags", "To Be Exported"]]
    max_risk = "LOW"
    risk_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    current_max_val = 1

    for item in audit_records:
        tags = item.get("suggestedTags", "")
        if isinstance(tags, list):
            tags = ", ".join(tags)
        item_risk = str(item.get("confidentialityRisk", "MEDIUM")).upper()
        if risk_rank.get(item_risk, 0) > current_max_val:
            current_max_val = risk_rank.get(item_risk, 0)
            max_risk = item_risk

        values.append([
            str(item.get("filename", "Unknown")),
            item_risk,
            str(tags),
            bool(item.get("toBeExported", False))
        ])

    # 4. Write Values
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A1:D",
        valueInputOption="USER_ENTERED",
        body={"values": values}
    ).execute()

    # 5. Format Header & Add Checkbox Validation
    row_count = len(values)
    format_requests = [
        # Header Style (Blue #4285F4 background, bold white text)
        {
            "repeatCell": {
                "range": {
                    "sheetId": target_sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 4
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.258, "green": 0.521, "blue": 0.956},
                        "textFormat": {"bold": True, "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}}
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)"
            }
        },
        # Checkbox Validation on Column D
        {
            "setDataValidation": {
                "range": {
                    "sheetId": target_sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": row_count,
                    "startColumnIndex": 3,
                    "endColumnIndex": 4
                },
                "rule": {
                    "condition": {"type": "BOOLEAN"},
                    "showCustomUi": True,
                    "strict": True
                }
            }
        },
        # Auto-resize columns A to D
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": target_sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": 4
                }
            }
        }
    ]

    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": format_requests}
    ).execute()

    # Step 7: Record milestone into Central Status Tracker
    try:
        handle_log_pipeline_status(
            mission_name=mission_name,
            status="AUDIT_READY",
            audit_url=spreadsheet_url,
            risk=max_risk,
            notes=f"Audit completed: {len(audit_records)} assets assessed"
        )
    except Exception as e:
        print(f"[Tracker] Step 7 auto-log warning in create_audit_sheet: {e}")

    return {
        "spreadsheetId": spreadsheet_id,
        "spreadsheetUrl": spreadsheet_url,
        "title": sheet_title,
        "rowsCount": len(audit_records)
    }


def handle_send_notification(recipient_email: str, mission_name: str, slide_url: str, sheet_url: str) -> Dict[str, Any]:
    creds = get_credentials()
    subject = f"[Completed] End of Mission Artifacts: {mission_name}"

    html_content = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px;">
      <h2 style="color: #1a73e8;">Mission Closure Automation Completed</h2>
      <p>Hello,</p>
      <p>The automated End-of-Mission analysis for <strong>{mission_name}</strong> has completed successfully. Your AI-generated artifacts are ready:</p>
      
      <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
        <tr>
          <td style="padding: 12px; border: 1px solid #ddd; background: #f8f9fa;">
            <strong>Agent 1: Executive One-Pager</strong>
          </td>
          <td style="padding: 12px; border: 1px solid #ddd;">
            <a href="{slide_url}" target="_blank" style="color: #1a73e8; font-weight: bold; text-decoration: none;">
              Open Google Slides &rarr;
            </a>
          </td>
        </tr>
        <tr>
          <td style="padding: 12px; border: 1px solid #ddd; background: #f8f9fa;">
            <strong>Agent 2: Knowledge & Confidentiality Checklist</strong>
          </td>
          <td style="padding: 12px; border: 1px solid #ddd;">
            <a href="{sheet_url}" target="_blank" style="color: #1a73e8; font-weight: bold; text-decoration: none;">
              Open Google Sheets &rarr;
            </a>
          </td>
        </tr>
      </table>

      <p style="font-size: 13px; color: #666;">
        <em>Next steps: Review the checkboxes in the Knowledge Checklist before final export to the internal repository.</em>
      </p>
    </div>
    """

    try:
        gmail_svc = get_gmail_service(creds)
        message = MIMEText(html_content, "html")
        message["to"] = recipient_email
        message["subject"] = subject
        raw_msg = base64.urlsafe_b64encode(message.as_bytes()).decode()

        gmail_svc.users().messages().send(userId="me", body={"raw": raw_msg}).execute()
        status = "sent_via_gmail_api"
    except Exception as mail_err:
        print(f"[Mail Warning] Gmail API send fallback: {mail_err}")
        status = f"simulated_delivery: {str(mail_err)}"

    # Step 7: Record milestone into Central Status Tracker
    try:
        handle_log_pipeline_status(
            mission_name=mission_name,
            status="NOTIFIED_LEAD",
            lead_email=recipient_email,
            deck_url=slide_url,
            audit_url=sheet_url,
            notes=f"Debrief artifacts emailed to {recipient_email}"
        )
    except Exception as e:
        print(f"[Tracker] Step 7 auto-log warning in send_notification: {e}")

    return {
        "status": status,
        "recipientEmail": recipient_email,
        "missionName": mission_name
    }

# =============================================================================
# FASTAPI APPLICATION FOR CLOUD RUN & AGENT DESIGNER
# =============================================================================

app = FastAPI(
    title="Artefact EOM Workspace Tool Service",
    description="OpenAPI tool connector for Google Cloud Agent Platform to manage Drive extraction, Slides generation, Sheets audit checklists, and Lead email notifications.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ExtractDocumentsRequest(BaseModel):
    folderId: Optional[str] = None
    folder_id: Optional[str] = None

    def get_folder_id(self) -> str:
        fid = self.folderId or self.folder_id
        if not fid:
            raise ValueError("folderId or folder_id is required")
        return fid

class GenerateSlideRequest(BaseModel):
    folderId: Optional[str] = None
    folder_id: Optional[str] = None
    missionName: Optional[str] = None
    mission_name: Optional[str] = None
    cardData: Optional[Any] = None
    card_data: Optional[Any] = None
    card: Optional[Any] = None
    templateId: Optional[str] = "197zP6K146fFlNSPDrDuHoUiKS9c0KODiypl_u27XWDQ"
    template_id: Optional[str] = None

    def get_folder_id(self) -> str:
        fid = self.folderId or self.folder_id
        if not fid:
            raise ValueError("folderId or folder_id is required")
        return fid

    def get_mission_name(self) -> str:
        return self.missionName or self.mission_name or "Mission"

    def get_card_data(self) -> Any:
        return self.cardData if self.cardData is not None else (self.card_data if self.card_data is not None else self.card)

    def get_template_id(self) -> str:
        return self.template_id or self.templateId or "197zP6K146fFlNSPDrDuHoUiKS9c0KODiypl_u27XWDQ"

class CreateAuditSheetRequest(BaseModel):
    folderId: Optional[str] = None
    folder_id: Optional[str] = None
    missionName: Optional[str] = None
    mission_name: Optional[str] = None
    auditRecords: Optional[Any] = None
    audit_records: Optional[Any] = None

    def get_folder_id(self) -> str:
        fid = self.folderId or self.folder_id
        if not fid:
            raise ValueError("folderId or folder_id is required")
        return fid

    def get_mission_name(self) -> str:
        return self.missionName or self.mission_name or "Mission"

    def get_audit_records(self) -> Any:
        return self.auditRecords if self.auditRecords is not None else self.audit_records

class SendNotificationRequest(BaseModel):
    recipientEmail: Optional[str] = None
    recipient_email: Optional[str] = None
    email: Optional[str] = None
    missionName: Optional[str] = None
    mission_name: Optional[str] = None
    slideUrl: Optional[str] = ""
    slide_url: Optional[str] = ""
    sheetUrl: Optional[str] = ""
    sheet_url: Optional[str] = ""

    def get_recipient_email(self) -> str:
        em = self.recipientEmail or self.recipient_email or self.email
        if not em:
            raise ValueError("recipientEmail or recipient_email is required")
        return em

    def get_mission_name(self) -> str:
        return self.missionName or self.mission_name or "Mission"

    def get_slide_url(self) -> str:
        return self.slideUrl or self.slide_url or ""

    def get_sheet_url(self) -> str:
        return self.sheetUrl or self.sheet_url or ""

class LogPipelineStatusRequest(BaseModel):
    missionName: Optional[str] = None
    mission_name: Optional[str] = None
    status: str
    client: Optional[str] = None
    leadEmail: Optional[str] = None
    lead_email: Optional[str] = None
    deckUrl: Optional[str] = None
    deck_url: Optional[str] = None
    auditUrl: Optional[str] = None
    audit_url: Optional[str] = None
    folderUrl: Optional[str] = None
    folder_url: Optional[str] = None
    risk: Optional[str] = None
    notes: Optional[str] = None

    def get_mission_name(self) -> str:
        return self.missionName or self.mission_name or "Mission"

    def get_lead_email(self) -> Optional[str]:
        return self.leadEmail or self.lead_email

    def get_deck_url(self) -> Optional[str]:
        return self.deckUrl or self.deck_url

    def get_audit_url(self) -> Optional[str]:
        return self.auditUrl or self.audit_url

    def get_folder_url(self) -> Optional[str]:
        return self.folderUrl or self.folder_url

@app.get("/")
@app.get("/healthz")
def health_check():
    return {"status": "ok", "service": "Artefact EOM Workspace Tool Service"}

@app.post("/extract-documents", operation_id="extract_folder_documents")
def api_extract_documents(req: ExtractDocumentsRequest):
    try:
        return handle_extract_documents(req.get_folder_id())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-slide", operation_id="generate_one_pager_slide")
def api_generate_slide(req: GenerateSlideRequest):
    try:
        return handle_generate_slide(
            folder_raw=req.get_folder_id(),
            mission_name=req.get_mission_name(),
            card=req.get_card_data(),
            template_id=req.get_template_id()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/create-audit-sheet", operation_id="create_audit_sheet")
def api_create_audit_sheet(req: CreateAuditSheetRequest):
    try:
        return handle_create_audit_sheet(
            folder_raw=req.get_folder_id(),
            mission_name=req.get_mission_name(),
            audit_records=req.get_audit_records()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/send-notification", operation_id="send_lead_notification")
def api_send_notification(req: SendNotificationRequest):
    try:
        return handle_send_notification(
            recipient_email=req.get_recipient_email(),
            mission_name=req.get_mission_name(),
            slide_url=req.get_slide_url(),
            sheet_url=req.get_sheet_url()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/log-pipeline-status", operation_id="log_pipeline_status")
@app.post("/pipeline/status")
def api_log_pipeline_status(req: LogPipelineStatusRequest):
    try:
        return handle_log_pipeline_status(
            mission_name=req.get_mission_name(),
            status=req.status,
            client=req.client,
            lead_email=req.get_lead_email(),
            deck_url=req.get_deck_url(),
            audit_url=req.get_audit_url(),
            folder_url=req.get_folder_url(),
            risk=req.risk,
            notes=req.notes
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
