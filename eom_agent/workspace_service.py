import os
import re
import json
import base64
from datetime import datetime
from email.mime.text import MIMEText
from typing import List, Optional, Dict, Any

import google.auth
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# =============================================================================
# AUTHENTICATION HELPER
# =============================================================================

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

    # 1. Create Spreadsheet
    ss_body = {
        "properties": {"title": sheet_title},
        "sheets": [{"properties": {"sheetId": 0, "title": "Knowledge Audit"}}]
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
    for item in audit_records:
        tags = item.get("suggestedTags", "")
        if isinstance(tags, list):
            tags = ", ".join(tags)
        values.append([
            str(item.get("filename", "Unknown")),
            str(item.get("confidentialityRisk", "MEDIUM")).upper(),
            str(tags),
            bool(item.get("toBeExported", False))
        ])

    # 4. Write Values
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="'Knowledge Audit'!A1:D",
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
        return {
            "status": "SENT",
            "recipientEmail": recipient_email,
            "missionName": mission_name
        }
    except Exception as e:
        print(f"[Email Error] Could not send via Gmail API: {e}")
        return {
            "status": "FAILED",
            "error": str(e),
            "recipientEmail": recipient_email
        }
