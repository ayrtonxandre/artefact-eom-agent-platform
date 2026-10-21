import os
import sys
import re
import json
import base64
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add workspace root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from eom_agent.bigquery_service import (
    query_upcoming_missions,
    detect_and_launch_upcoming_missions
)
from eom_agent.workspace_service import (
    check_debrief_doc_completion,
    build_reminder_email_html,
    handle_send_reminder,
    scan_and_send_reminders
)

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

class LaunchMissionRequest(BaseModel):
    missionName: Optional[str] = None
    mission_name: Optional[str] = None
    leadEmail: Optional[str] = None
    lead_email: Optional[str] = None
    client: Optional[str] = None
    industry: Optional[str] = None
    teamEmails: Optional[Any] = None
    team_emails: Optional[Any] = None
    folderId: Optional[str] = None
    folder_id: Optional[str] = None
    parentFolderId: Optional[str] = None
    parent_folder_id: Optional[str] = None
    deadlineDate: Optional[str] = None
    deadline_date: Optional[str] = None
    notes: Optional[str] = None

    def get_mission_name(self) -> str:
        name = self.missionName or self.mission_name
        if not name:
            raise ValueError("missionName or mission_name is required")
        return name

    def get_lead_email(self) -> str:
        em = self.leadEmail or self.lead_email
        if not em:
            raise ValueError("leadEmail or lead_email is required")
        return em

    def get_team_emails(self) -> Optional[Any]:
        return self.teamEmails if self.teamEmails is not None else self.team_emails

    def get_folder_id(self) -> Optional[str]:
        return self.folderId or self.folder_id

    def get_parent_folder_id(self) -> Optional[str]:
        return self.parentFolderId or self.parent_folder_id

    def get_deadline_date(self) -> Optional[str]:
        return self.deadlineDate or self.deadline_date

class DetectMissionsRequest(BaseModel):
    daysAhead: Optional[int] = 7
    days_ahead: Optional[int] = None
    targetDate: Optional[str] = None
    target_date: Optional[str] = None
    dateStart: Optional[str] = None
    date_start: Optional[str] = None
    dateEnd: Optional[str] = None
    date_end: Optional[str] = None
    clientName: Optional[str] = None
    client_name: Optional[str] = None
    leadEmail: Optional[str] = None
    lead_email: Optional[str] = None
    limit: Optional[int] = 50

    def get_days_ahead(self) -> Optional[int]:
        if self.targetDate or self.target_date or (self.dateStart and self.dateEnd):
            return None
        return self.days_ahead if self.days_ahead is not None else self.daysAhead

    def get_target_date(self) -> Optional[str]:
        return self.targetDate or self.target_date

    def get_date_start(self) -> Optional[str]:
        return self.dateStart or self.date_start

    def get_date_end(self) -> Optional[str]:
        return self.dateEnd or self.date_end

    def get_client_name(self) -> Optional[str]:
        return self.clientName or self.client_name

    def get_lead_email(self) -> Optional[str]:
        return self.leadEmail or self.lead_email

class DetectAndLaunchRequest(BaseModel):
    daysAhead: Optional[int] = 7
    days_ahead: Optional[int] = None
    targetDate: Optional[str] = None
    target_date: Optional[str] = None
    dateStart: Optional[str] = None
    date_start: Optional[str] = None
    dateEnd: Optional[str] = None
    date_end: Optional[str] = None
    clientName: Optional[str] = None
    client_name: Optional[str] = None
    autoLaunch: Optional[bool] = True
    auto_launch: Optional[bool] = None
    dryRun: Optional[bool] = False
    dry_run: Optional[bool] = None
    overrideLeadEmail: Optional[str] = None
    override_lead_email: Optional[str] = None
    parentFolderId: Optional[str] = None
    parent_folder_id: Optional[str] = None
    trackerId: Optional[str] = None
    tracker_id: Optional[str] = None
    limit: Optional[int] = 10

    def get_days_ahead(self) -> Optional[int]:
        if self.targetDate or self.target_date or (self.dateStart and self.dateEnd):
            return None
        return self.days_ahead if self.days_ahead is not None else self.daysAhead

    def get_target_date(self) -> Optional[str]:
        return self.targetDate or self.target_date

    def get_date_start(self) -> Optional[str]:
        return self.dateStart or self.date_start

    def get_date_end(self) -> Optional[str]:
        return self.dateEnd or self.date_end

    def get_client_name(self) -> Optional[str]:
        return self.clientName or self.client_name

    def get_auto_launch(self) -> bool:
        if self.auto_launch is not None:
            return self.auto_launch
        return self.autoLaunch if self.autoLaunch is not None else True

    def get_dry_run(self) -> bool:
        if self.dry_run is not None:
            return self.dry_run
        return self.dryRun if self.dryRun is not None else False

    def get_override_lead_email(self) -> Optional[str]:
        return self.overrideLeadEmail or self.override_lead_email

    def get_parent_folder_id(self) -> Optional[str]:
        return self.parentFolderId or self.parent_folder_id

    def get_tracker_id(self) -> Optional[str]:
        return self.trackerId or self.tracker_id

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

class CheckDebriefStatusRequest(BaseModel):
    docId: Optional[str] = None
    doc_id: Optional[str] = None
    folderId: Optional[str] = None
    folder_id: Optional[str] = None
    missionName: Optional[str] = None
    mission_name: Optional[str] = None

    def get_target_id(self) -> str:
        tid = self.docId or self.doc_id or self.folderId or self.folder_id or self.missionName or self.mission_name
        if not tid:
            raise ValueError("docId, folderId, or missionName is required")
        return tid

class SendReminderRequest(BaseModel):
    missionName: Optional[str] = None
    mission_name: Optional[str] = None
    leadEmail: Optional[str] = None
    lead_email: Optional[str] = None
    client: Optional[str] = None
    docId: Optional[str] = None
    doc_id: Optional[str] = None
    folderId: Optional[str] = None
    folder_id: Optional[str] = None
    daysRemaining: Optional[int] = 3
    days_remaining: Optional[int] = None
    deadlineDate: Optional[str] = None
    deadline_date: Optional[str] = None
    overrideLeadEmail: Optional[str] = None
    override_lead_email: Optional[str] = None
    dryRun: Optional[bool] = False
    dry_run: Optional[bool] = None
    industry: Optional[str] = None
    trackerId: Optional[str] = None
    tracker_id: Optional[str] = None

    def get_mission_name(self) -> str:
        name = self.missionName or self.mission_name
        if not name:
            raise ValueError("missionName or mission_name is required")
        return name

    def get_lead_email(self) -> str:
        em = self.leadEmail or self.lead_email
        if not em:
            raise ValueError("leadEmail or lead_email is required")
        return em

    def get_days_remaining(self) -> int:
        return self.days_remaining if self.days_remaining is not None else (self.daysRemaining or 3)

    def get_dry_run(self) -> bool:
        if self.dry_run is not None:
            return self.dry_run
        return self.dryRun if self.dryRun is not None else False

    def get_override_lead_email(self) -> Optional[str]:
        return self.overrideLeadEmail or self.override_lead_email

class TriggerRemindersRequest(BaseModel):
    daysAhead: Optional[int] = None
    days_ahead: Optional[int] = None
    forceSend: Optional[bool] = False
    force_send: Optional[bool] = None
    dryRun: Optional[bool] = False
    dry_run: Optional[bool] = None
    overrideLeadEmail: Optional[str] = None
    override_lead_email: Optional[str] = None
    trackerId: Optional[str] = None
    tracker_id: Optional[str] = None
    limit: Optional[int] = 20

    def get_days_ahead(self) -> Optional[int]:
        return self.days_ahead if self.days_ahead is not None else self.daysAhead

    def get_force_send(self) -> bool:
        if self.force_send is not None:
            return self.force_send
        return self.forceSend if self.forceSend is not None else False

    def get_dry_run(self) -> bool:
        if self.dry_run is not None:
            return self.dry_run
        return self.dryRun if self.dryRun is not None else False

    def get_override_lead_email(self) -> Optional[str]:
        return self.overrideLeadEmail or self.override_lead_email

    def get_tracker_id(self) -> Optional[str]:
        return self.trackerId or self.tracker_id


@app.get("/")
@app.get("/healthz")
def health_check():
    return {"status": "ok", "service": "Artefact EOM Workspace Tool Service"}

@app.post("/missions/detect", operation_id="detect_upcoming_missions")
def api_detect_missions(req: DetectMissionsRequest):
    try:
        return query_upcoming_missions(
            days_ahead=req.get_days_ahead(),
            target_date=req.get_target_date(),
            date_start=req.get_date_start(),
            date_end=req.get_date_end(),
            client_name=req.get_client_name(),
            lead_email=req.get_lead_email(),
            limit=req.limit or 50
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/missions/upcoming")
def api_get_upcoming_missions(
    days_ahead: Optional[int] = 7,
    target_date: Optional[str] = None,
    client: Optional[str] = None,
    limit: Optional[int] = 50
):
    try:
        return query_upcoming_missions(
            days_ahead=days_ahead if not target_date else None,
            target_date=target_date,
            client_name=client,
            limit=limit or 50
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/missions/detect-and-launch", operation_id="detect_and_launch_missions")
def api_detect_and_launch(req: DetectAndLaunchRequest):
    try:
        return detect_and_launch_upcoming_missions(
            days_ahead=req.get_days_ahead() or 7,
            target_date=req.get_target_date(),
            date_start=req.get_date_start(),
            date_end=req.get_date_end(),
            client_name=req.get_client_name(),
            auto_launch=req.get_auto_launch(),
            dry_run=req.get_dry_run(),
            override_lead_email=req.get_override_lead_email(),
            parent_folder_id=req.get_parent_folder_id(),
            tracker_id=req.get_tracker_id(),
            limit=req.limit or 10
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/launch-mission", operation_id="launch_mission_kickoff")
def api_launch_mission(req: LaunchMissionRequest):
    try:
        return handle_launch_mission(
            mission_name=req.get_mission_name(),
            lead_email=req.get_lead_email(),
            client=req.client,
            team_emails=req.get_team_emails(),
            folder_id=req.get_folder_id(),
            parent_folder_id=req.get_parent_folder_id(),
            deadline_date=req.get_deadline_date(),
            notes=req.notes,
            industry=req.industry
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/missions/check-debrief", operation_id="check_mission_debrief_status")
def api_check_debrief(req: CheckDebriefStatusRequest):
    try:
        return check_debrief_doc_completion(req.get_target_id())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/send-reminder", operation_id="send_mission_reminder")
def api_send_reminder(req: SendReminderRequest):
    try:
        return handle_send_reminder(
            mission_name=req.get_mission_name(),
            lead_email=req.get_lead_email(),
            client=req.client,
            doc_id=req.docId or req.doc_id,
            folder_id=req.folderId or req.folder_id,
            days_remaining=req.get_days_remaining(),
            deadline_date=req.deadlineDate or req.deadline_date,
            override_lead_email=req.get_override_lead_email(),
            dry_run=req.get_dry_run(),
            industry=req.industry,
            tracker_id=req.trackerId or req.tracker_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/missions/reminders", operation_id="trigger_eom_reminders")
def api_trigger_reminders(req: TriggerRemindersRequest):
    try:
        return scan_and_send_reminders(
            days_ahead=req.get_days_ahead(),
            force_send=req.get_force_send(),
            dry_run=req.get_dry_run(),
            override_lead_email=req.get_override_lead_email(),
            tracker_id=req.get_tracker_id(),
            limit=req.limit or 20
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
