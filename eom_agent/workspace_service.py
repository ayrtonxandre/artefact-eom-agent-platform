import os
import re
import json
import base64
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import List, Optional, Dict, Any

import google.auth
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaInMemoryUpload

# =============================================================================
# AUTHENTICATION HELPER & CONSTANTS
# =============================================================================

CENTRAL_TRACKER_NAME = "[Artefact EOM] Central Pipeline Status Tracker"
CENTRAL_TRACKER_TAB = "Pipeline Status Log"
DEFAULT_TRACKER_ID = "1IDMXRrgiONxaxqB1N-ahRMoiHx4tqfB9vxhSxyhnH7s"
DEFAULT_PARENT_FOLDER_ID = "1oqx6AT98K36xUOM2G_UYKBRGMfv_ub-U"
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

def build_debrief_doc_html(
    mission_name: str,
    client: str,
    lead_email: str,
    team_emails: List[str],
    deadline_str: str,
    visuals_url: str,
    industry: Optional[str] = None
) -> str:
    """Generates corporate Artefact debrief HTML template to be converted into a Google Doc."""
    team_display = ", ".join(team_emails) if team_emails else "Équipe Projet Artefact"
    industry_row = f"""
    <tr>
      <td style="font-weight: bold; background-color: #f1f5f9;">Secteur / Industrie</td>
      <td>{industry}</td>
    </tr>""" if industry else ""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: Arial, Helvetica, sans-serif;
    color: #1e293b;
    line-height: 1.6;
    margin: 20px;
  }}
  h1 {{
    color: #0f172a;
    font-size: 22pt;
    font-weight: bold;
    border-bottom: 2px solid #1a73e8;
    padding-bottom: 8px;
    margin-bottom: 16px;
  }}
  h2 {{
    color: #1a73e8;
    font-size: 15pt;
    font-weight: bold;
    margin-top: 26px;
    margin-bottom: 10px;
  }}
  table.meta {{
    width: 100%;
    border-collapse: collapse;
    background-color: #f8fafc;
    border: 1px solid #cbd5e1;
    margin-bottom: 20px;
  }}
  table.meta td {{
    padding: 8px 12px;
    font-size: 11pt;
    border: 1px solid #cbd5e1;
  }}
  table.callout {{
    width: 100%;
    border-collapse: collapse;
    background-color: #eff6ff;
    border: 1px solid #93c5fd;
    margin-bottom: 24px;
  }}
  table.callout td {{
    padding: 12px 16px;
    font-size: 11pt;
    color: #1e3a8a;
  }}
  .guidance {{
    color: #475569;
    font-size: 10.5pt;
    margin-bottom: 8px;
  }}
  .placeholder {{
    color: #94a3b8;
    font-style: italic;
    background-color: #ffffff;
    border: 1px dashed #cbd5e1;
    padding: 14px 18px;
    margin-bottom: 20px;
  }}
  ul {{
    margin-top: 4px;
    margin-bottom: 8px;
  }}
  li {{
    margin-bottom: 4px;
  }}
</style>
</head>
<body>
  <h1>Artefact End-of-Mission Debrief</h1>

  <table class="meta">
    <tr>
      <td style="width: 25%; font-weight: bold; background-color: #f1f5f9;">Mission</td>
      <td style="width: 75%;">{mission_name}</td>
    </tr>
    <tr>
      <td style="font-weight: bold; background-color: #f1f5f9;">Client</td>
      <td>{client}</td>
    </tr>{industry_row}
    <tr>
      <td style="font-weight: bold; background-color: #f1f5f9;">Manager de Mission</td>
      <td>{lead_email}</td>
    </tr>
    <tr>
      <td style="font-weight: bold; background-color: #f1f5f9;">Équipe Projet</td>
      <td>{team_display}</td>
    </tr>
    <tr>
      <td style="font-weight: bold; background-color: #f1f5f9;">Date Limite Souhaitée</td>
      <td style="color: #b91c1c; font-weight: bold;">{deadline_str}</td>
    </tr>
  </table>

  <table class="callout">
    <tr>
      <td>
        <strong>🎯 Objectif du Débrief de Mission (Standard One-Pager Artefact) :</strong><br>
        Ce document constitue le support unique de débrief de fin de mission. Il sera analysé par les agents IA autonomes Artefact pour générer :
        <ol style="margin-top: 6px; margin-bottom: 6px;">
          <li>Le <strong>One-Pager exécutif Google Slides</strong> valorisant la mission auprès du leadership et des clients.</li>
          <li>La <strong>Checklist d'Audit et de Confidentialité Google Sheets</strong> pour sécuriser et indexer les livrables dans la base de connaissances Artefact.</li>
        </ol>
        <em>Veuillez renseigner les 3 sections ci-dessous avec des faits précis et des métriques chiffrées.</em>
      </td>
    </tr>
  </table>

  <h2>1. Challenge (Contexte & Problématique Client)</h2>
  <div class="guidance">
    <strong>Questions guides :</strong>
    <ul>
      <li>Quel était l'enjeu business et stratégique du client ? Quel était le point de douleur initial ?</li>
      <li>Quelles étaient les contraintes majeures (réglementaires, volumétrie de données, legacy tech, calendrier) ?</li>
      <li>Pourquoi le client a-t-il fait appel à l'expertise Artefact ?</li>
    </ul>
  </div>
  <div class="placeholder">
    [Rédigez ici le contexte, les enjeux business du client et les problématiques majeures rencontrées...]
  </div>

  <h2>2. Solution (Livrables & Architecture Déployée)</h2>
  <div class="guidance">
    <strong>Questions guides :</strong>
    <ul>
      <li>Quelle solution technique ou fonctionnelle a été conçue et déployée (Data Platform, GenAI, Dashboards, MLOps...) ?</li>
      <li>Quels sont les livrables concrets produits par Artefact (pipelines BigQuery, modèles Vertex AI, cockpits Looker...) ?</li>
      <li>Comment s'organisait l'équipe Artefact (rôles, méthodologie agile, accompagnement au changement) ?</li>
    </ul>
  </div>
  <div class="placeholder">
    [Détaillez ici la solution déployée, les technologies utilisées et les principaux livrables produits...]
  </div>

  <h2>3. Results & Impact (KPIs & Valeur Métier Générée)</h2>
  <div class="guidance">
    <strong>Questions guides :</strong>
    <ul>
      <li>Quels sont les impacts chiffrés et mesurables (ex : % de temps gagné, ROI financier, économies en €, volume de requêtes traitées) ?</li>
      <li>Quelle est l'échelle du déploiement (nombre d'utilisateurs actifs, pays ou entités déployées) ?</li>
      <li>Quels sont les retours de la part des sponsors clients et les prochaines étapes recommandées (Next Steps) ?</li>
    </ul>
  </div>
  <div class="placeholder">
    [Indiquez ici les chiffres clés, KPIs d'impact, retours clients et recommandations pour la suite...]
  </div>

  <h2>4. Visuels & Schémas d'Architecture</h2>
  <div class="guidance">
    <strong>Assets attendus :</strong>
    <ul>
      <li>Schémas d'architecture technique (Cloud GCP / Data / AI).</li>
      <li>Captures d'écrans de dashboards, interfaces UI ou démos d'outils.</li>
      <li>Graphiques de performance ou workflow fonctionnel.</li>
    </ul>
    <p>👉 <strong>Déposez directement vos fichiers dans le sous-dossier Drive dédié :</strong><br>
    <a href="{visuals_url}" style="color: #1a73e8; font-weight: bold;">Accéder au sous-dossier Drive : 01_Visuals & Diagrams &rarr;</a></p>
  </div>
</body>
</html>
"""

def build_kickoff_email_html(
    mission_name: str,
    client: str,
    lead_email: str,
    team_emails: List[str],
    deadline_str: str,
    doc_url: str,
    visuals_url: str,
    folder_url: str,
    folder_name: str,
    industry: Optional[str] = None
) -> str:
    """Generates corporate Artefact launch / kickoff email in HTML format."""
    team_greeting = f"Bonjour l'équipe {mission_name}," if team_emails else "Bonjour,"
    sub_info = f"Mission : <strong>{mission_name}</strong> | Client : <strong>{client}</strong>"
    if industry:
        sub_info += f" | Secteur : <strong>{industry}</strong>"
    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 650px; margin: 0 auto; color: #1e293b; line-height: 1.6;">
      <div style="background-color: #0f172a; padding: 24px; border-radius: 8px 8px 0 0; text-align: left;">
        <span style="background-color: #1e293b; color: #38bdf8; font-size: 11px; font-weight: bold; padding: 4px 8px; border-radius: 4px; text-transform: uppercase; letter-spacing: 0.5px;">Artefact EOM Pipeline</span>
        <h1 style="color: #ffffff; margin: 10px 0 0 0; font-size: 20px; font-weight: 600;">Lancement du Débrief One-Pager de Fin de Mission</h1>
        <p style="color: #94a3b8; margin: 6px 0 0 0; font-size: 13px;">{sub_info}</p>
      </div>
      
      <div style="padding: 24px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 8px 8px; background-color: #ffffff;">
        <p style="font-size: 15px; margin-top: 0;">{team_greeting}</p>
        <p>Votre mission <strong>{mission_name}</strong> approche de son terme (environ 7 jours avant clôture). Afin de valoriser le travail réalisé et de capitaliser sur vos livrables, l'espace de débrief automatisé <strong>Artefact EOM Agent</strong> a été initialisé.</p>
        
        <div style="background-color: #f8fafc; border-left: 4px solid #1a73e8; padding: 14px 18px; margin: 20px 0; border-radius: 4px;">
          <h3 style="margin: 0 0 8px 0; color: #0f172a; font-size: 15px;">📋 2 actions attendues d'ici le <span style="color: #b91c1c;">{deadline_str}</span> :</h3>
          <ol style="margin: 0; padding-left: 20px; font-size: 14px;">
            <li style="margin-bottom: 8px;">
              <strong>Compléter le Google Doc Debrief</strong> structuré en 3 volets clés :
              <ul style="margin-top: 4px; color: #475569;">
                <li><strong>1. Challenge :</strong> Contexte client & problématiques résolues</li>
                <li><strong>2. Solution :</strong> Livrables, stack tech & architecture déployée</li>
                <li><strong>3. Results :</strong> Métriques chiffrées, ROI & impact métier</li>
              </ul>
            </li>
            <li>
              <strong>Déposer vos visuels & schémas</strong> d'architecture dans le sous-dossier dédié pour illustrer le deck final.
            </li>
          </ol>
        </div>

        <!-- Call to Action Buttons -->
        <table style="width: 100%; margin: 25px 0;" cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding-right: 8px; width: 50%;">
              <a href="{doc_url}" target="_blank" style="display: block; text-align: center; background-color: #1a73e8; color: #ffffff; padding: 12px 14px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13px;">
                📄 Ouvrir le Google Doc Debrief &rarr;
              </a>
            </td>
            <td style="padding-left: 8px; width: 50%;">
              <a href="{visuals_url}" target="_blank" style="display: block; text-align: center; background-color: #0f172a; color: #ffffff; padding: 12px 14px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13px;">
                🖼️ Déposer les Visuels & Schémas &rarr;
              </a>
            </td>
          </tr>
        </table>

        <div style="background-color: #f1f5f9; padding: 12px 16px; border-radius: 6px; font-size: 13px; color: #475569;">
          📁 <strong>Dossier Drive de la Mission :</strong> <a href="{folder_url}" target="_blank" style="color: #1a73e8; text-decoration: underline;">{folder_name}</a><br>
          🤖 <strong>Étape suivante :</strong> Dès vos inputs complétés, le pipeline multi-agent générera le One-Pager exécutif Google Slides et la checklist de conformité interne.
        </div>

        <p style="font-size: 12px; color: #94a3b8; margin-top: 25px; margin-bottom: 0; text-align: center;">
          Artefact End-of-Mission Automation • Notification automatique générée par l'agent IA EOM
        </p>
      </div>
    </div>
    """

def handle_launch_mission(
    mission_name: str,
    lead_email: str,
    client: Optional[str] = None,
    team_emails: Optional[Any] = None,
    folder_id: Optional[str] = None,
    parent_folder_id: Optional[str] = None,
    deadline_date: Optional[str] = None,
    notes: Optional[str] = None,
    industry: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Step 2 in Target EOM Process: Initializes the mission workspace and dispatches kickoff email.
    1. Locates or creates the mission workspace folder in Google Drive.
    2. Creates the '01_Visuals & Diagrams' subfolder.
    3. Creates the structured 3-section Debrief Google Doc template (Challenge, Solution, Results).
    4. Dispatches the branded kickoff email to the mission manager (lead_email) and team (team_emails).
    5. Records the milestone 'LAUNCHED' in the Central Pipeline Status Tracker spreadsheet.
    """
    creds = get_credentials()
    drive_svc = get_drive_service(creds)
    gmail_svc = get_gmail_service(creds)

    clean_mission = mission_name.strip()
    clean_client = (client or clean_mission.replace("Mission", "").strip()).strip()
    clean_lead = lead_email.strip()

    # Parse and normalize team emails
    normalized_team_emails: List[str] = []
    if isinstance(team_emails, str):
        try:
            parsed = json.loads(team_emails)
            if isinstance(parsed, list):
                normalized_team_emails = [str(e).strip() for e in parsed if "@" in str(e)]
            else:
                normalized_team_emails = [e.strip() for e in team_emails.split(",") if "@" in e]
        except Exception:
            normalized_team_emails = [e.strip() for e in team_emails.split(",") if "@" in e]
    elif isinstance(team_emails, list):
        normalized_team_emails = [str(e).strip() for e in team_emails if "@" in str(e)]

    # Compute deadline
    if deadline_date:
        deadline_str = str(deadline_date).strip()
    else:
        deadline_str = (datetime.now() + timedelta(days=7)).strftime("%d/%m/%Y")

    # 1. Resolve or Create Mission Drive Folder
    mission_folder_id = None
    mission_folder_url = ""
    mission_folder_name = ""

    if folder_id:
        target_fid = parse_folder_id(folder_id)
        try:
            meta = drive_svc.files().get(
                fileId=target_fid,
                fields="id, name, webViewLink",
                supportsAllDrives=True
            ).execute()
            mission_folder_id = meta["id"]
            mission_folder_name = meta["name"]
            mission_folder_url = meta.get("webViewLink", f"https://drive.google.com/drive/folders/{mission_folder_id}")
        except Exception as e:
            print(f"[Launch Mission] Warning: could not access specified folder_id {folder_id}: {e}")

    if not mission_folder_id:
        base_parent = parse_folder_id(parent_folder_id or DEFAULT_PARENT_FOLDER_ID)
        target_folder_name = f"[EOM] {clean_client} - {clean_mission}" if clean_client not in clean_mission else f"[EOM] {clean_mission}"
        
        # Check if already exists in parent
        try:
            query = f"'{base_parent}' in parents and name = '{target_folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            res = drive_svc.files().list(
                q=query,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                fields="files(id, name, webViewLink)"
            ).execute()
            existing = res.get("files", [])
            if existing:
                mission_folder_id = existing[0]["id"]
                mission_folder_name = existing[0]["name"]
                mission_folder_url = existing[0].get("webViewLink", f"https://drive.google.com/drive/folders/{mission_folder_id}")
        except Exception as search_err:
            print(f"[Launch Mission] Search folder warning: {search_err}")

        # If not existing, create it
        if not mission_folder_id:
            body = {
                "name": target_folder_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [base_parent]
            }
            new_folder = drive_svc.files().create(
                body=body,
                supportsAllDrives=True,
                fields="id, name, webViewLink"
            ).execute()
            mission_folder_id = new_folder["id"]
            mission_folder_name = new_folder["name"]
            mission_folder_url = new_folder.get("webViewLink", f"https://drive.google.com/drive/folders/{mission_folder_id}")

    # 2. Resolve or Create Visuals Subfolder
    visuals_name = "01_Visuals & Diagrams"
    visuals_folder_id = None
    visuals_folder_url = ""
    try:
        q_vis = f"'{mission_folder_id}' in parents and name = '{visuals_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        res_vis = drive_svc.files().list(
            q=q_vis,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            fields="files(id, name, webViewLink)"
        ).execute()
        existing_vis = res_vis.get("files", [])
        if existing_vis:
            visuals_folder_id = existing_vis[0]["id"]
            visuals_folder_url = existing_vis[0].get("webViewLink", f"https://drive.google.com/drive/folders/{visuals_folder_id}")
        else:
            new_vis = drive_svc.files().create(
                body={
                    "name": visuals_name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [mission_folder_id]
                },
                supportsAllDrives=True,
                fields="id, name, webViewLink"
            ).execute()
            visuals_folder_id = new_vis["id"]
            visuals_folder_url = new_vis.get("webViewLink", f"https://drive.google.com/drive/folders/{visuals_folder_id}")
    except Exception as vis_err:
        print(f"[Launch Mission] Visuals subfolder warning: {vis_err}")
        visuals_folder_url = mission_folder_url

    # 3. Resolve or Create Debrief Template Google Doc
    doc_title = f"[Debrief Template] {clean_mission} - EOM One-Pager Input"
    doc_id = None
    doc_url = ""
    try:
        q_doc = f"'{mission_folder_id}' in parents and name = '{doc_title}' and mimeType = 'application/vnd.google-apps.document' and trashed = false"
        res_doc = drive_svc.files().list(
            q=q_doc,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            fields="files(id, name, webViewLink)"
        ).execute()
        existing_doc = res_doc.get("files", [])
        if existing_doc:
            doc_id = existing_doc[0]["id"]
            doc_url = existing_doc[0].get("webViewLink", f"https://docs.google.com/document/d/{doc_id}/edit")
        else:
            doc_html = build_debrief_doc_html(
                mission_name=clean_mission,
                client=clean_client,
                lead_email=clean_lead,
                team_emails=normalized_team_emails,
                deadline_str=deadline_str,
                visuals_url=visuals_folder_url,
                industry=industry
            )
            media = MediaInMemoryUpload(doc_html.encode("utf-8"), mimetype="text/html")
            new_doc = drive_svc.files().create(
                body={
                    "name": doc_title,
                    "mimeType": "application/vnd.google-apps.document",
                    "parents": [mission_folder_id]
                },
                media_body=media,
                supportsAllDrives=True,
                fields="id, name, webViewLink"
            ).execute()
            doc_id = new_doc["id"]
            doc_url = new_doc.get("webViewLink", f"https://docs.google.com/document/d/{doc_id}/edit")
    except Exception as doc_err:
        print(f"[Launch Mission] Debrief Doc creation warning: {doc_err}")

    # 4. Dispatch Kickoff Email via Gmail API
    email_status = "NOT_SENT"
    try:
        email_html = build_kickoff_email_html(
            mission_name=clean_mission,
            client=clean_client,
            lead_email=clean_lead,
            team_emails=normalized_team_emails,
            deadline_str=deadline_str,
            doc_url=doc_url,
            visuals_url=visuals_folder_url,
            folder_url=mission_folder_url,
            folder_name=mission_folder_name or clean_mission,
            industry=industry
        )
        msg = MIMEText(email_html, "html")
        msg["to"] = clean_lead
        if normalized_team_emails:
            msg["cc"] = ", ".join(normalized_team_emails)
        msg["subject"] = f"[Kickoff EOM] Lancement du One-Pager de fin de mission - {clean_mission}"
        raw_msg = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        gmail_svc.users().messages().send(userId="me", body={"raw": raw_msg}).execute()
        email_status = "SENT"
    except Exception as mail_err:
        print(f"[Launch Mission] Kickoff email error: {mail_err}")
        email_status = f"FAILED: {mail_err}"

    # 5. Record Milestone in Central Pipeline Status Tracker (Step 7)
    tracker_notes = notes or f"Kickoff email sent to {clean_lead}. Debrief Doc and Visuals subfolder ready. Deadline: {deadline_str}"
    try:
        handle_log_pipeline_status(
            mission_name=clean_mission,
            status="LAUNCHED",
            client=clean_client,
            lead_email=clean_lead,
            folder_url=mission_folder_url,
            notes=tracker_notes
        )
    except Exception as log_err:
        print(f"[Launch Mission] Status logging warning: {log_err}")

    return {
        "status": "LAUNCHED",
        "missionName": clean_mission,
        "client": clean_client,
        "leadEmail": clean_lead,
        "teamEmails": normalized_team_emails,
        "deadlineDate": deadline_str,
        "folderId": mission_folder_id,
        "folderName": mission_folder_name,
        "folderUrl": mission_folder_url,
        "docId": doc_id,
        "docUrl": doc_url,
        "visualsFolderId": visuals_folder_id,
        "visualsFolderUrl": visuals_folder_url,
        "emailStatus": email_status
    }


def check_debrief_doc_completion(target_id_or_url: str, creds=None) -> Dict[str, Any]:
    """
    Step 3 in Target EOM Process: Inspects a Google Doc (or mission folder) to verify debrief completion.
    Analyzes the 3 core pillars (Challenge, Solution, Results) for remaining template placeholders
    and substantive written content.

    Returns:
        Dict with keys:
            docId: Google Doc ID
            docName: Document title
            docUrl: Web edit link
            isCompleted: True if all 3 sections are filled and placeholders removed
            completionRate: Float between 0.0 and 1.0 (e.g. 0.67 if 2 of 3 filled)
            completedSections: List of completed section names (e.g. ["Challenge"])
            missingSections: List of incomplete section names (e.g. ["Solution", "Results"])
            sections: Detailed status per section (filled, character count, preview)
            totalCharacters: Substantive content character count
    """
    drive_svc = get_drive_service(creds)
    raw_id = parse_folder_id(target_id_or_url)
    
    # 1. Resolve whether input is Folder or Document
    doc_id = None
    doc_name = ""
    try:
        meta = drive_svc.files().get(
            fileId=raw_id,
            fields="id, name, mimeType, webViewLink",
            supportsAllDrives=True
        ).execute()
        
        mime = meta.get("mimeType", "")
        if mime == "application/vnd.google-apps.folder":
            # Search for debrief doc inside folder
            q = f"'{raw_id}' in parents and mimeType = 'application/vnd.google-apps.document' and trashed = false"
            res = drive_svc.files().list(
                q=q,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                fields="files(id, name, webViewLink)"
            ).execute()
            files = res.get("files", [])
            if not files:
                return {
                    "docId": None,
                    "docName": None,
                    "docUrl": None,
                    "isCompleted": False,
                    "completionRate": 0.0,
                    "completedSections": [],
                    "missingSections": ["Challenge", "Solution", "Results"],
                    "sections": {},
                    "totalCharacters": 0,
                    "error": f"No Google Doc found in folder {raw_id}"
                }
            # Prefer doc starting with [Debrief
            debrief_files = [f for f in files if "[Debrief" in f.get("name", "")]
            target_doc = debrief_files[0] if debrief_files else files[0]
            doc_id = target_doc["id"]
            doc_name = target_doc["name"]
        else:
            doc_id = meta["id"]
            doc_name = meta["name"]
    except Exception as e:
        return {
            "docId": raw_id,
            "isCompleted": False,
            "completionRate": 0.0,
            "completedSections": [],
            "missingSections": ["Challenge", "Solution", "Results"],
            "sections": {},
            "totalCharacters": 0,
            "error": f"Could not inspect document or folder: {e}"
        }

    # 2. Export text content via Google Drive API
    try:
        raw_data = drive_svc.files().export(fileId=doc_id, mimeType="text/plain").execute()
        doc_text = raw_data.decode("utf-8", errors="ignore")
    except Exception as exp_err:
        return {
            "docId": doc_id,
            "docName": doc_name,
            "docUrl": f"https://docs.google.com/document/d/{doc_id}/edit",
            "isCompleted": False,
            "completionRate": 0.0,
            "completedSections": [],
            "missingSections": ["Challenge", "Solution", "Results"],
            "sections": {},
            "totalCharacters": 0,
            "error": f"Failed to export Google Doc text: {exp_err}"
        }

    # 3. Helper to parse section content between headers
    def extract_section_text(text: str, start_pattern: str, end_pattern: Optional[str]) -> str:
        m_start = re.search(start_pattern, text, re.IGNORECASE)
        if not m_start:
            return ""
        sub = text[m_start.end():]
        if end_pattern:
            m_end = re.search(end_pattern, sub, re.IGNORECASE)
            if m_end:
                sub = sub[:m_end.start()]
        return sub.strip()

    c_raw = extract_section_text(doc_text, r"1\.\s*Challenge", r"2\.\s*Solution")
    s_raw = extract_section_text(doc_text, r"2\.\s*Solution", r"3\.\s*Results")
    r_raw = extract_section_text(doc_text, r"3\.\s*Results", r"4\.\s*Visuels")

    def analyze_section(section_raw: str, placeholder_regex: str, min_chars: int = 25) -> Dict[str, Any]:
        has_placeholder = bool(re.search(placeholder_regex, section_raw, re.IGNORECASE))
        
        # Clean guidance prompts and bullet questions
        cleaned = re.sub(r"^\s*\([^\)]+\)", "", section_raw).strip()
        cleaned = re.sub(r"Questions guides\s*:[\s\S]*?(?=\r?\n\r?\n|\[|[A-Z0-9À-ÖØ-öø-ÿ]|$)", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^\s*[\*\-•][^\r\n]+", "", cleaned, flags=re.MULTILINE).strip()
        user_content = re.sub(placeholder_regex, "", cleaned, flags=re.IGNORECASE).strip()
        
        user_len = len(user_content)
        filled = (not has_placeholder) and (user_len >= min_chars)
        preview = user_content[:150].replace("\r", " ").replace("\n", " ").strip()
        
        return {
            "filled": filled,
            "hasPlaceholder": has_placeholder,
            "characterCount": user_len,
            "preview": preview if filled else ""
        }

    c_stat = analyze_section(c_raw, r"\[Rédigez ici[^\]]*\]")
    s_stat = analyze_section(s_raw, r"\[Détaillez ici[^\]]*\]")
    r_stat = analyze_section(r_raw, r"\[Indiquez ici[^\]]*\]")

    sections = {
        "Challenge": c_stat,
        "Solution": s_stat,
        "Results": r_stat
    }

    completed_sections = [name for name, stat in sections.items() if stat["filled"]]
    missing_sections = [name for name, stat in sections.items() if not stat["filled"]]
    is_completed = (len(missing_sections) == 0)
    completion_rate = round(len(completed_sections) / 3.0, 2)
    total_chars = sum(stat["characterCount"] for stat in sections.values())

    return {
        "docId": doc_id,
        "docName": doc_name,
        "docUrl": f"https://docs.google.com/document/d/{doc_id}/edit",
        "isCompleted": is_completed,
        "completionRate": completion_rate,
        "completedSections": completed_sections,
        "missingSections": missing_sections,
        "sections": sections,
        "totalCharacters": total_chars
    }


def build_reminder_email_html(
    mission_name: str,
    client: str,
    lead_email: str,
    days_remaining: int,
    deadline_str: str,
    doc_url: str,
    visuals_url: str,
    folder_url: str,
    folder_name: str,
    missing_sections: List[str],
    completion_rate: float,
    industry: Optional[str] = None
) -> str:
    """Generates corporate Artefact reminder email in HTML format for J-3 / J-1 relances."""
    sub_info = f"Mission : <strong>{mission_name}</strong> | Client : <strong>{client}</strong>"
    if industry:
        sub_info += f" | Secteur : <strong>{industry}</strong>"

    # Dynamic urgency badge & theme
    if days_remaining <= 1:
        badge_bg = "#dc2626"
        badge_text = "🚨 DERNIER RAPPEL J-1 • CLÔTURE DEMAIN"
        urgency_msg = f"Votre mission se termine <strong>demain ({deadline_str})</strong>."
    else:
        badge_bg = "#d97706"
        badge_text = f"⏳ RAPPEL J-3 • PLUS QUE {days_remaining} JOURS"
        urgency_msg = f"Votre mission approche de son terme dans <strong>{days_remaining} jours ({deadline_str})</strong>."

    pct_display = int(completion_rate * 100)
    missing_display = ", ".join(missing_sections) if missing_sections else "Validation finale"

    missing_bullets = ""
    for sec in missing_sections:
        desc = ""
        if sec == "Challenge":
            desc = "Contexte client, enjeux stratégiques & problématiques initiales"
        elif sec == "Solution":
            desc = "Architecture technique déployée, stack IA/Data & livrables Artefact"
        elif sec == "Results":
            desc = "Métriques chiffrées, ROI, impact business & sponsors feedback"
        missing_bullets += f"<li style='margin-bottom: 6px;'><strong>{sec} :</strong> {desc}</li>"

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 650px; margin: 0 auto; color: #1e293b; line-height: 1.6;">
      <div style="background-color: #0f172a; padding: 24px; border-radius: 8px 8px 0 0; text-align: left;">
        <span style="background-color: {badge_bg}; color: #ffffff; font-size: 11px; font-weight: bold; padding: 4px 8px; border-radius: 4px; text-transform: uppercase; letter-spacing: 0.5px;">{badge_text}</span>
        <h1 style="color: #ffffff; margin: 10px 0 0 0; font-size: 20px; font-weight: 600;">Relance : Débrief One-Pager en attente</h1>
        <p style="color: #94a3b8; margin: 6px 0 0 0; font-size: 13px;">{sub_info}</p>
      </div>
      
      <div style="padding: 24px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 8px 8px; background-color: #ffffff;">
        <p style="font-size: 15px; margin-top: 0;">Bonjour {lead_email},</p>
        <p>{urgency_msg} Afin de générer le <strong>One-Pager exécutif Google Slides</strong> valorisant la mission auprès du leadership Artefact et d'indexer vos livrables, merci de finaliser le support de débrief.</p>
        
        <!-- Progress bar -->
        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px 18px; margin: 18px 0;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 13px;">
            <span><strong>État d'avancement du Débrief :</strong></span>
            <span style="font-weight: bold; color: {badge_bg};">{pct_display}% complété</span>
          </div>
          <div style="width: 100%; background-color: #e2e8f0; height: 10px; border-radius: 5px; overflow: hidden;">
            <div style="width: {pct_display}%; background-color: {'#16a34a' if pct_display >= 100 else '#1a73e8'}; height: 100%;"></div>
          </div>
        </div>

        <div style="background-color: #fff7ed; border-left: 4px solid #f97316; padding: 14px 18px; margin: 20px 0; border-radius: 4px;">
          <h3 style="margin: 0 0 8px 0; color: #9a3412; font-size: 15px;">⚠️ Sections restant à compléter :</h3>
          <ul style="margin: 0; padding-left: 20px; font-size: 14px; color: #431407;">
            {missing_bullets}
          </ul>
        </div>

        <!-- Call to Action Buttons -->
        <table style="width: 100%; margin: 25px 0;" cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding-right: 8px; width: 50%;">
              <a href="{doc_url}" target="_blank" style="display: block; text-align: center; background-color: #1a73e8; color: #ffffff; padding: 12px 14px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13px;">
                📄 Compléter le Google Doc Debrief &rarr;
              </a>
            </td>
            <td style="padding-left: 8px; width: 50%;">
              <a href="{visuals_url}" target="_blank" style="display: block; text-align: center; background-color: #0f172a; color: #ffffff; padding: 12px 14px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13px;">
                🖼️ Déposer les Visuels & Schémas &rarr;
              </a>
            </td>
          </tr>
        </table>

        <div style="background-color: #f1f5f9; padding: 12px 16px; border-radius: 6px; font-size: 13px; color: #475569;">
          📁 <strong>Dossier Drive de la Mission :</strong> <a href="{folder_url}" target="_blank" style="color: #1a73e8; text-decoration: underline;">{folder_name}</a><br>
          🤖 <strong>Dès que vos 3 sections sont remplies</strong>, le pipeline autonome génère automatiquement votre One-Pager exécutif et la checklist d'audit.
        </div>

        <p style="font-size: 12px; color: #94a3b8; margin-top: 25px; margin-bottom: 0; text-align: center;">
          Artefact End-of-Mission Automation • Relance automatique générée par l'agent IA EOM
        </p>
      </div>
    </div>
    """


def handle_send_reminder(
    mission_name: str,
    lead_email: str,
    client: Optional[str] = None,
    doc_id: Optional[str] = None,
    folder_id: Optional[str] = None,
    days_remaining: int = 3,
    deadline_date: Optional[str] = None,
    override_lead_email: Optional[str] = None,
    team_emails: Optional[Any] = None,
    dry_run: bool = False,
    industry: Optional[str] = None,
    tracker_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Step 3 in Target EOM Process: Sends automated reminder email (J-3 or J-1) to the mission lead.
    1. Inspects the debrief Google Doc completion.
    2. If debrief doc is already 100% completed, updates tracker to DEBRIEF_COMPLETED and skips email.
    3. If incomplete, dispatches branded Artefact reminder HTML email with missing sections callout.
    4. Updates Central Pipeline Status Tracker milestone (REMINDER_J3 or REMINDER_J1).
    """
    creds = get_credentials()
    drive_svc = get_drive_service(creds)
    gmail_svc = get_gmail_service(creds)

    clean_mission = mission_name.strip()
    clean_client = (client or clean_mission.replace("Mission", "").replace("[", "").replace("]", "").strip()).strip()
    clean_lead = lead_email.strip()
    recipient_email = (override_lead_email or clean_lead).strip()

    # Determine deadline string
    if deadline_date:
        deadline_str = str(deadline_date).strip()
    else:
        deadline_str = (datetime.now() + timedelta(days=days_remaining)).strftime("%d/%m/%Y")

    # 1. Resolve doc & folder IDs
    target_doc_id = doc_id
    mission_folder_id = folder_id
    folder_name = clean_mission
    folder_url = ""
    visuals_url = ""

    if not target_doc_id and folder_id:
        f_clean = parse_folder_id(folder_id)
        mission_folder_id = f_clean
        doc_inspect = check_debrief_doc_completion(f_clean, creds=creds)
        target_doc_id = doc_inspect.get("docId")

    if not mission_folder_id and target_doc_id:
        try:
            doc_meta = drive_svc.files().get(
                fileId=target_doc_id,
                fields="parents, webViewLink",
                supportsAllDrives=True
            ).execute()
            parents = doc_meta.get("parents", [])
            if parents:
                mission_folder_id = parents[0]
        except Exception:
            pass

    if mission_folder_id:
        folder_url = f"https://drive.google.com/drive/folders/{mission_folder_id}"
        # Locate visuals subfolder
        try:
            q_vis = f"'{mission_folder_id}' in parents and name = '01_Visuals & Diagrams' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            res_vis = drive_svc.files().list(q=q_vis, supportsAllDrives=True, fields="files(id, webViewLink)").execute()
            v_files = res_vis.get("files", [])
            if v_files:
                visuals_url = v_files[0].get("webViewLink", folder_url)
        except Exception:
            visuals_url = folder_url
    else:
        visuals_url = folder_url

    # 2. Inspect document completion
    doc_inspect = check_debrief_doc_completion(target_doc_id or mission_folder_id, creds=creds) if (target_doc_id or mission_folder_id) else {}
    is_completed = doc_inspect.get("isCompleted", False)
    missing_sections = doc_inspect.get("missingSections", ["Challenge", "Solution", "Results"])
    completion_rate = doc_inspect.get("completionRate", 0.0)
    doc_url = doc_inspect.get("docUrl", f"https://docs.google.com/document/d/{target_doc_id}/edit" if target_doc_id else "")

    # If already completed, update tracker and do not spam lead
    if is_completed:
        log_notes = f"Debrief Doc verified 100% completed ({doc_inspect.get('totalCharacters', 0)} chars). Ready for One-Pager generation."
        handle_log_pipeline_status(
            mission_name=clean_mission,
            status="DEBRIEF_COMPLETED",
            client=clean_client,
            lead_email=clean_lead,
            folder_url=folder_url,
            notes=log_notes,
            tracker_id=tracker_id
        )
        return {
            "status": "DEBRIEF_COMPLETED",
            "action": "SKIPPED_ALREADY_COMPLETED",
            "missionName": clean_mission,
            "leadEmail": clean_lead,
            "completionRate": 1.0,
            "message": "Debrief Doc is fully completed. No reminder email needed."
        }

    # 3. Urgency milestone
    milestone_status = "REMINDER_J1" if days_remaining <= 1 else "REMINDER_J3"

    if dry_run:
        return {
            "status": "SIMULATED",
            "action": "SIMULATED_REMINDER_READY",
            "missionName": clean_mission,
            "client": clean_client,
            "leadEmail": recipient_email,
            "daysRemaining": days_remaining,
            "milestone": milestone_status,
            "missingSections": missing_sections,
            "completionRate": completion_rate,
            "docUrl": doc_url
        }

    # 4. Dispatch Email via Gmail API
    email_status = "NOT_SENT"
    try:
        email_html = build_reminder_email_html(
            mission_name=clean_mission,
            client=clean_client,
            lead_email=recipient_email,
            days_remaining=days_remaining,
            deadline_str=deadline_str,
            doc_url=doc_url,
            visuals_url=visuals_url or folder_url,
            folder_url=folder_url,
            folder_name=folder_name,
            missing_sections=missing_sections,
            completion_rate=completion_rate,
            industry=industry
        )
        msg = MIMEText(email_html, "html")
        msg["to"] = recipient_email
        reminder_tag = "J-1" if days_remaining <= 1 else "J-3"
        msg["subject"] = f"[{reminder_tag} EOM] Relance Débrief One-Pager - {clean_mission}"
        raw_msg = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        gmail_svc.users().messages().send(userId="me", body={"raw": raw_msg}).execute()
        email_status = "SENT"
    except Exception as mail_err:
        print(f"[Reminder] Email send error: {mail_err}")
        email_status = f"FAILED: {mail_err}"

    # 5. Update milestone in Central Status Tracker
    tracker_note = f"Relance {milestone_status} envoyée à {recipient_email}. Manque : {', '.join(missing_sections)}"
    if override_lead_email:
        tracker_note += f" (Lead réel: {clean_lead})"

    try:
        handle_log_pipeline_status(
            mission_name=clean_mission,
            status=milestone_status,
            client=clean_client,
            lead_email=clean_lead,
            folder_url=folder_url,
            notes=tracker_note,
            tracker_id=tracker_id
        )
    except Exception as log_err:
        print(f"[Reminder] Status logging warning: {log_err}")

    return {
        "status": milestone_status,
        "action": "REMINDER_SENT",
        "missionName": clean_mission,
        "client": clean_client,
        "leadEmail": recipient_email,
        "daysRemaining": days_remaining,
        "missingSections": missing_sections,
        "completionRate": completion_rate,
        "docUrl": doc_url,
        "emailStatus": email_status
    }


def scan_and_send_reminders(
    target_days: Optional[List[int]] = None,
    days_ahead: Optional[int] = None,
    force_send: bool = False,
    dry_run: bool = False,
    override_lead_email: Optional[str] = None,
    tracker_id: Optional[str] = None,
    limit: int = 20
) -> Dict[str, Any]:
    """
    Automated Step 3 Scanner: Scans Central Pipeline Status Tracker for active missions (LAUNCHED, REMINDER_J3),
    verifies debrief completion status, and dispatches J-3 / J-1 reminders to mission managers.
    """
    from .bigquery_service import query_mission_by_id_or_name

    creds = get_credentials()
    sheets_svc = get_sheets_service(creds)
    target_tracker_id = tracker_id or os.environ.get("CENTRAL_TRACKER_ID", DEFAULT_TRACKER_ID)

    allowed_target_days = [days_ahead] if days_ahead is not None else (target_days or [1, 3])

    # 1. Fetch rows from Central Status Tracker
    try:
        res = sheets_svc.spreadsheets().values().get(
            spreadsheetId=target_tracker_id,
            range=f"'{CENTRAL_TRACKER_TAB}'!A:J"
        ).execute()
        rows = res.get("values", [])
    except Exception as e:
        return {"status": "FAILED", "error": f"Could not read tracker sheet: {e}"}

    if not rows or len(rows) <= 1:
        return {"status": "COMPLETED", "message": "No tracked missions found.", "processed": []}

    processed_missions = []
    reminders_sent = 0
    debriefs_completed = 0
    skipped_count = 0

    today = datetime.now().date()

    for r in rows[1:]:
        if len(processed_missions) >= limit:
            break
        if not r or not r[0].strip():
            continue

        m_name = r[0].strip()
        m_client = r[1] if len(r) > 1 else ""
        m_lead = r[2] if len(r) > 2 else ""
        m_status = r[3] if len(r) > 3 else ""
        m_folder_url = r[6] if len(r) > 6 else ""
        m_notes = r[9] if len(r) > 9 else ""

        # Only process missions awaiting debrief input
        if m_status not in ("LAUNCHED", "REMINDER_J3"):
            continue

        # 2. Determine remaining days
        days_remaining = None
        bq_meta = query_mission_by_id_or_name(m_name)
        if bq_meta and bq_meta.get("days_until_end") is not None:
            days_remaining = int(bq_meta["days_until_end"])
        else:
            # Try to parse deadline from notes e.g. "Deadline: 28/10/2026"
            match_dl = re.search(r"(\d{2}/\d{2}/\d{4})", m_notes)
            if match_dl:
                try:
                    dt = datetime.strptime(match_dl.group(1), "%d/%m/%Y").date()
                    days_remaining = (dt - today).days
                except Exception:
                    pass

        if days_remaining is None:
            days_remaining = 3  # Fallback default

        # 3. Check if due for reminder
        is_due = force_send
        target_reminder_tier = 1 if days_remaining <= 1 else 3

        if not is_due:
            if target_reminder_tier in allowed_target_days:
                if target_reminder_tier == 1 and m_status != "REMINDER_J1":
                    is_due = True
                elif target_reminder_tier == 3 and m_status == "LAUNCHED":
                    is_due = True

        if not is_due:
            skipped_count += 1
            processed_missions.append({
                "missionName": m_name,
                "status": m_status,
                "daysRemaining": days_remaining,
                "action": "SKIPPED_NOT_DUE"
            })
            continue

        # 4. Dispatch or simulate reminder
        folder_id = parse_folder_id(m_folder_url) if m_folder_url else None
        rem_res = handle_send_reminder(
            mission_name=m_name,
            lead_email=m_lead,
            client=m_client,
            folder_id=folder_id,
            days_remaining=days_remaining,
            override_lead_email=override_lead_email,
            dry_run=dry_run,
            tracker_id=target_tracker_id
        )

        if rem_res.get("status") == "DEBRIEF_COMPLETED":
            debriefs_completed += 1
        elif rem_res.get("action") == "REMINDER_SENT" or rem_res.get("action") == "SIMULATED_REMINDER_READY":
            reminders_sent += 1

        processed_missions.append(rem_res)

    return {
        "status": "COMPLETED",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "totalChecked": len(rows) - 1,
        "remindersSent": reminders_sent,
        "debriefsCompleted": debriefs_completed,
        "skippedCount": skipped_count,
        "dryRun": dry_run,
        "missions": processed_missions
    }


def handle_extract_documents(folder_raw: str) -> Dict[str, Any]:
    folder_id = parse_folder_id(folder_raw)
    drive_svc = get_drive_service()

    # 1. Fetch Folder Metadata
    folder_meta = drive_svc.files().get(
        fileId=folder_id,
        fields="id, name, mimeType",
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
