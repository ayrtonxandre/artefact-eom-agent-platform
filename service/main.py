import os
import sys
import re
import io
import json
import base64
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import List, Optional, Dict, Any

# Prevent deprecated oauth2client crash on mismatched OpenSSL in Anaconda/system Python
if "oauth2client" not in sys.modules:
    sys.modules["oauth2client"] = None

try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    import httplib2
    httplib2.CA_CERTS = certifi.where()
    import ssl
    ssl._create_default_https_context = lambda *args, **kwargs: ssl.create_default_context(cafile=certifi.where())
except Exception:
    pass

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add workspace root and local dir to sys.path
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from eom_agent.bigquery_service import (
    query_upcoming_missions,
    detect_and_launch_upcoming_missions,
    MOCK_MISSIONS
)
from eom_agent.workspace_service import (
    CENTRAL_TRACKER_NAME,
    CENTRAL_TRACKER_TAB,
    DEFAULT_TRACKER_ID,
    DEFAULT_PARENT_FOLDER_ID,
    TRACKER_HEADERS,
    SCOPES,
    DISPATCH_SECURITY_EXEMPT_MISSIONS,
    is_dispatch_security_exempt,
    get_credentials,
    get_drive_service,
    get_docs_service,
    get_slides_service,
    get_sheets_service,
    get_gmail_service,
    parse_folder_id,
    format_card_text,
    get_or_create_central_tracker_sheet,
    handle_log_pipeline_status,
    build_debrief_doc_html,
    build_kickoff_email_html,
    build_antichamber_email_html,
    handle_send_antichamber_notification,
    handle_launch_mission,
    check_debrief_doc_completion,
    build_reminder_email_html,
    handle_send_reminder,
    scan_and_send_reminders,
    handle_extract_documents,
    handle_generate_slide,
    handle_create_audit_sheet,
    build_completed_email_html,
    handle_send_notification,
    handle_prefill_debrief_doc,
    handle_wrapup_mission,
)

import google.auth
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaInMemoryUpload

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
    originalLeadEmail: Optional[str] = None
    original_lead_email: Optional[str] = None
    ccEmails: Optional[Any] = None
    cc_emails: Optional[Any] = None

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

    def get_original_lead_email(self) -> Optional[str]:
        return self.originalLeadEmail or self.original_lead_email

    def get_cc_emails(self) -> Optional[Any]:
        return self.ccEmails if self.ccEmails is not None else self.cc_emails

    def get_team_emails(self) -> Optional[Any]:
        return self.teamEmails if self.teamEmails is not None else self.team_emails

    def get_folder_id(self) -> Optional[str]:
        return self.folderId or self.folder_id

    def get_parent_folder_id(self) -> Optional[str]:
        return self.parentFolderId or self.parent_folder_id

    def get_deadline_date(self) -> Optional[str]:
        return self.deadlineDate or self.deadline_date

class SendAntichamberNotificationRequest(BaseModel):
    leadEmail: Optional[str] = None
    lead_email: Optional[str] = None
    client: str
    missions: Optional[List[Dict[str, Any]]] = None
    antichamberUrl: Optional[str] = None
    antichamber_url: Optional[str] = None
    ccEmails: Optional[List[str]] = None
    cc_emails: Optional[List[str]] = None

    def get_lead_email(self) -> str:
        em = self.leadEmail or self.lead_email
        if not em:
            raise ValueError("leadEmail or lead_email is required")
        return em

    def get_antichamber_url(self) -> Optional[str]:
        return self.antichamberUrl or self.antichamber_url

    def get_cc_emails(self) -> Optional[List[str]]:
        return self.ccEmails or self.cc_emails

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
    exactDate: Optional[bool] = False
    exact_date: Optional[bool] = None
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

    def get_exact_date(self) -> bool:
        if self.exact_date is not None:
            return self.exact_date
        return self.exactDate if self.exactDate is not None else False

    def get_parent_folder_id(self) -> Optional[str]:
        return self.parentFolderId or self.parent_folder_id

    def get_tracker_id(self) -> Optional[str]:
        return self.trackerId or self.tracker_id


class ValidateDebriefRequest(BaseModel):
    folderId: Optional[str] = None
    folder_id: Optional[str] = None
    docId: Optional[str] = None
    doc_id: Optional[str] = None
    client: Optional[str] = None
    leadEmail: Optional[str] = None
    lead_email: Optional[str] = None
    missionName: Optional[str] = None
    mission_name: Optional[str] = None
    ccEmails: Optional[Any] = None
    cc_emails: Optional[Any] = None

    def get_folder_id(self) -> str:
        fid = self.folderId or self.folder_id
        if not fid:
            raise ValueError("folderId or folder_id is required")
        return fid

    def get_doc_id(self) -> Optional[str]:
        return self.docId or self.doc_id

    def get_lead_email(self) -> Optional[str]:
        return self.leadEmail or self.lead_email

    def get_mission_name(self) -> Optional[str]:
        return self.missionName or self.mission_name

    def get_cc_emails(self) -> Optional[Any]:
        return self.ccEmails if self.ccEmails is not None else self.cc_emails


class PrefillDebriefRequest(BaseModel):
    folderId: Optional[str] = None
    folder_id: Optional[str] = None
    client: Optional[str] = None
    leadEmail: Optional[str] = None
    lead_email: Optional[str] = None
    missionName: Optional[str] = None
    mission_name: Optional[str] = None
    teamEmails: Optional[Any] = None
    team_emails: Optional[Any] = None
    deadlineDate: Optional[str] = None
    deadline_date: Optional[str] = None
    industry: Optional[str] = None
    prefilledPayload: Optional[Dict[str, Any]] = None
    prefilled_payload: Optional[Dict[str, Any]] = None
    originalLeadEmail: Optional[str] = None
    original_lead_email: Optional[str] = None
    ccEmails: Optional[Any] = None
    cc_emails: Optional[Any] = None
    notes: Optional[str] = None

    def get_folder_id(self) -> str:
        fid = self.folderId or self.folder_id
        if not fid:
            raise ValueError("folderId or folder_id is required")
        return fid

    def get_lead_email(self) -> Optional[str]:
        return self.leadEmail or self.lead_email

    def get_mission_name(self) -> Optional[str]:
        return self.missionName or self.mission_name

    def get_team_emails(self) -> Optional[Any]:
        return self.teamEmails if self.teamEmails is not None else self.team_emails

    def get_deadline_date(self) -> Optional[str]:
        return self.deadlineDate or self.deadline_date

    def get_prefilled_payload(self) -> Optional[Dict[str, Any]]:
        return self.prefilledPayload if self.prefilledPayload is not None else self.prefilled_payload

    def get_original_lead_email(self) -> Optional[str]:
        return self.originalLeadEmail or self.original_lead_email

    def get_cc_emails(self) -> Optional[Any]:
        return self.ccEmails if self.ccEmails is not None else self.cc_emails


class WrapupMissionRequest(BaseModel):
    folderId: Optional[str] = None
    folder_id: Optional[str] = None
    missionName: Optional[str] = None
    mission_name: Optional[str] = None
    client: Optional[str] = None
    leadEmail: Optional[str] = None
    lead_email: Optional[str] = None
    docId: Optional[str] = None
    doc_id: Optional[str] = None
    personaCards: Optional[Dict[str, Any]] = None
    persona_cards: Optional[Dict[str, Any]] = None
    personaImages: Optional[Dict[str, Any]] = None
    persona_images: Optional[Dict[str, Any]] = None
    auditRecords: Optional[List[Dict[str, Any]]] = None
    audit_records: Optional[List[Dict[str, Any]]] = None
    industry: Optional[str] = None
    ccEmails: Optional[Any] = None
    cc_emails: Optional[Any] = None

    def get_folder_id(self) -> str:
        fid = self.folderId or self.folder_id
        if not fid:
            raise ValueError("folderId or folder_id is required")
        return fid

    def get_mission_name(self) -> Optional[str]:
        return self.missionName or self.mission_name

    def get_lead_email(self) -> Optional[str]:
        return self.leadEmail or self.lead_email

    def get_doc_id(self) -> Optional[str]:
        return self.docId or self.doc_id

    def get_persona_cards(self) -> Optional[Dict[str, Any]]:
        return self.personaCards if self.personaCards is not None else self.persona_cards

    def get_persona_images(self) -> Optional[Dict[str, Any]]:
        return self.personaImages if self.personaImages is not None else self.persona_images

    def get_audit_records(self) -> Optional[List[Dict[str, Any]]]:
        return self.auditRecords if self.auditRecords is not None else self.audit_records

    def get_cc_emails(self) -> Optional[Any]:
        return self.ccEmails if self.ccEmails is not None else self.cc_emails


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
    templateId: Optional[str] = "1DH-zXzB9CmaYB-p0CyXJDR-gdeJ6gSvylM-76IPfkEY"
    template_id: Optional[str] = None
    personae: Optional[List[str]] = None
    client: Optional[str] = None

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
        return self.template_id or self.templateId or "1DH-zXzB9CmaYB-p0CyXJDR-gdeJ6gSvylM-76IPfkEY"

    def get_personae(self) -> Optional[List[str]]:
        return self.personae

    def get_client(self) -> Optional[str]:
        return self.client

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
    client: Optional[str] = None
    folderUrl: Optional[str] = None
    folder_url: Optional[str] = None
    industry: Optional[str] = None
    ccEmails: Optional[Any] = None
    cc_emails: Optional[Any] = None
    cc: Optional[Any] = None

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

    def get_client(self) -> Optional[str]:
        return self.client or None

    def get_folder_url(self) -> Optional[str]:
        return self.folderUrl or self.folder_url or None

    def get_industry(self) -> Optional[str]:
        return self.industry or None

    def get_cc_emails(self) -> Optional[Any]:
        return self.ccEmails or self.cc_emails or self.cc or None

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


class ValidateDebriefRequest(BaseModel):
    folderId: Optional[str] = None
    folder_id: Optional[str] = None
    docId: Optional[str] = None
    doc_id: Optional[str] = None
    client: Optional[str] = None
    leadEmail: Optional[str] = None
    lead_email: Optional[str] = None
    missionName: Optional[str] = None
    mission_name: Optional[str] = None
    ccEmails: Optional[Any] = None
    cc_emails: Optional[Any] = None

    def get_folder_id(self) -> str:
        fid = self.folderId or self.folder_id
        if not fid:
            raise ValueError("folderId or folder_id is required")
        return fid

    def get_doc_id(self) -> Optional[str]:
        return self.docId or self.doc_id

    def get_lead_email(self) -> Optional[str]:
        return self.leadEmail or self.lead_email

    def get_mission_name(self) -> Optional[str]:
        return self.missionName or self.mission_name

    def get_cc_emails(self) -> Optional[Any]:
        return self.ccEmails if self.ccEmails is not None else self.cc_emails


class PrefillDebriefRequest(BaseModel):
    folderId: Optional[str] = None
    folder_id: Optional[str] = None
    client: Optional[str] = None
    leadEmail: Optional[str] = None
    lead_email: Optional[str] = None
    missionName: Optional[str] = None
    mission_name: Optional[str] = None
    teamEmails: Optional[Any] = None
    team_emails: Optional[Any] = None
    deadlineDate: Optional[str] = None
    deadline_date: Optional[str] = None
    industry: Optional[str] = None
    prefilledPayload: Optional[Dict[str, Any]] = None
    prefilled_payload: Optional[Dict[str, Any]] = None
    originalLeadEmail: Optional[str] = None
    original_lead_email: Optional[str] = None
    ccEmails: Optional[Any] = None
    cc_emails: Optional[Any] = None
    notes: Optional[str] = None

    def get_folder_id(self) -> str:
        fid = self.folderId or self.folder_id
        if not fid:
            raise ValueError("folderId or folder_id is required")
        return fid

    def get_lead_email(self) -> Optional[str]:
        return self.leadEmail or self.lead_email

    def get_mission_name(self) -> Optional[str]:
        return self.missionName or self.mission_name

    def get_team_emails(self) -> Optional[Any]:
        return self.teamEmails if self.teamEmails is not None else self.team_emails

    def get_deadline_date(self) -> Optional[str]:
        return self.deadlineDate or self.deadline_date

    def get_prefilled_payload(self) -> Optional[Dict[str, Any]]:
        return self.prefilledPayload if self.prefilledPayload is not None else self.prefilled_payload

    def get_original_lead_email(self) -> Optional[str]:
        return self.originalLeadEmail or self.original_lead_email

    def get_cc_emails(self) -> Optional[Any]:
        return self.ccEmails if self.ccEmails is not None else self.cc_emails


class WrapupMissionRequest(BaseModel):
    folderId: Optional[str] = None
    folder_id: Optional[str] = None
    missionName: Optional[str] = None
    mission_name: Optional[str] = None
    client: Optional[str] = None
    leadEmail: Optional[str] = None
    lead_email: Optional[str] = None
    docId: Optional[str] = None
    doc_id: Optional[str] = None
    personaCards: Optional[Dict[str, Any]] = None
    persona_cards: Optional[Dict[str, Any]] = None
    personaImages: Optional[Dict[str, Any]] = None
    persona_images: Optional[Dict[str, Any]] = None
    auditRecords: Optional[List[Dict[str, Any]]] = None
    audit_records: Optional[List[Dict[str, Any]]] = None
    industry: Optional[str] = None
    ccEmails: Optional[Any] = None
    cc_emails: Optional[Any] = None

    def get_folder_id(self) -> str:
        fid = self.folderId or self.folder_id
        if not fid:
            raise ValueError("folderId or folder_id is required")
        return fid

    def get_mission_name(self) -> Optional[str]:
        return self.missionName or self.mission_name

    def get_lead_email(self) -> Optional[str]:
        return self.leadEmail or self.lead_email

    def get_doc_id(self) -> Optional[str]:
        return self.docId or self.doc_id

    def get_persona_cards(self) -> Optional[Dict[str, Any]]:
        return self.personaCards if self.personaCards is not None else self.persona_cards

    def get_persona_images(self) -> Optional[Dict[str, Any]]:
        return self.personaImages if self.personaImages is not None else self.persona_images

    def get_audit_records(self) -> Optional[List[Dict[str, Any]]]:
        return self.auditRecords if self.auditRecords is not None else self.audit_records

    def get_cc_emails(self) -> Optional[Any]:
        return self.ccEmails if self.ccEmails is not None else self.cc_emails



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
    limit: Optional[int] = 50,
    exact_date: Optional[bool] = False
):
    try:
        return query_upcoming_missions(
            days_ahead=days_ahead if not target_date else None,
            target_date=target_date,
            client_name=client,
            limit=limit or 50,
            exact_date=exact_date if exact_date is not None else False
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
            limit=req.limit or 10,
            exact_date=req.get_exact_date()
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
            industry=req.industry,
            original_lead_email=req.get_original_lead_email(),
            cc_emails=req.get_cc_emails()
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
            template_id=req.get_template_id(),
            personae=req.get_personae(),
            client=req.get_client()
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
            sheet_url=req.get_sheet_url(),
            client=req.get_client(),
            folder_url=req.get_folder_url(),
            industry=req.get_industry(),
            cc_emails=req.get_cc_emails()
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


# =============================================================================
# ANTICHAMBER (PRE-KICKOFF STAGING) HTML RENDERERS & ENDPOINTS
# =============================================================================

def render_antichamber_page(
    client: str,
    lead_email: str,
    candidate_missions: List[Dict[str, Any]]
) -> str:
    """Renders the responsive Artefact Antichamber staging web portal."""
    mission_cards_html = ""
    default_names = []

    for idx, m in enumerate(candidate_missions):
        mid = m.get("mission_id", f"MIS-{idx+1}")
        mname = m.get("mission_name", "Mission")
        edate = m.get("end_date", "J+7")
        default_names.append(mname)
        
        mission_cards_html += f"""
        <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px 16px; margin-bottom: 10px; display: flex; align-items: flex-start; gap: 12px; transition: border-color 0.2s;">
          <input type="checkbox" id="m_{idx}" name="selected_mission_ids" value="{mid}" data-name="{mname}" checked onchange="handleCheckboxChange()" style="margin-top: 3px; width: 18px; height: 18px; accent-color: #1a73e8; cursor: pointer;">
          <label for="m_{idx}" style="cursor: pointer; flex: 1;">
            <div style="display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px;">
              <strong style="color: #0f172a; font-size: 14px;">{mname}</strong>
              <span style="background-color: #f1f5f9; color: #475569; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px; font-family: monospace;">{mid}</span>
            </div>
            <div style="font-size: 12px; color: #64748b; margin-top: 4px;">
              📅 Fin prévue : <strong>{edate}</strong> &bull; Client : {client}
            </div>
          </label>
        </div>
        """

    initial_title = " + ".join(default_names) if default_names else f"Mission {client}"

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Antichambre EOM • {client}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #f8fafc;
      color: #1e293b;
      margin: 0;
      padding: 30px 15px;
      line-height: 1.5;
    }}
    .container {{
      max-width: 680px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 10px;
      border: 1px solid #e2e8f0;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
      overflow: hidden;
    }}
    .header {{
      background-color: #0f172a;
      color: #ffffff;
      padding: 24px 28px;
    }}
    .badge {{
      display: inline-block;
      background-color: #3b82f6;
      color: #ffffff;
      font-size: 11px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 4px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 8px;
    }}
    .header h1 {{
      margin: 0;
      font-size: 22px;
      font-weight: 700;
      color: #ffffff;
    }}
    .header p {{
      margin: 6px 0 0 0;
      color: #94a3b8;
      font-size: 13px;
    }}
    .content {{
      padding: 28px;
    }}
    .section-title {{
      font-size: 15px;
      font-weight: 700;
      color: #0f172a;
      margin: 22px 0 10px 0;
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .section-title:first-of-type {{
      margin-top: 0;
    }}
    .radio-card {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 12px 14px;
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      gap: 10px;
      cursor: pointer;
    }}
    .radio-card:hover {{
      border-color: #cbd5e1;
    }}
    .radio-card input {{
      accent-color: #1a73e8;
      width: 16px;
      height: 16px;
      cursor: pointer;
    }}
    .form-group {{
      margin-bottom: 18px;
    }}
    .form-group label {{
      display: block;
      font-size: 13px;
      font-weight: 600;
      color: #334155;
      margin-bottom: 6px;
    }}
    .form-control {{
      width: 100%;
      box-sizing: border-box;
      padding: 10px 12px;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      font-size: 14px;
      color: #0f172a;
      background: #ffffff;
    }}
    .form-control:focus {{
      outline: none;
      border-color: #1a73e8;
      box-shadow: 0 0 0 3px rgba(26, 115, 232, 0.15);
    }}
    .tip-box {{
      background-color: #eff6ff;
      border-left: 4px solid #1a73e8;
      padding: 12px 14px;
      border-radius: 4px;
      font-size: 13px;
      color: #1e3a8a;
      margin-top: 8px;
    }}
    .helper-text {{
      font-size: 12px;
      color: #64748b;
      margin-top: 5px;
    }}
    .btn-submit {{
      width: 100%;
      background-color: #1a73e8;
      color: #ffffff;
      border: none;
      padding: 14px;
      border-radius: 6px;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
      transition: background-color 0.2s;
      margin-top: 24px;
    }}
    .btn-submit:hover {{
      background-color: #1557b0;
    }}
    .btn-reset {{
      background-color: #f1f5f9;
      color: #475569;
      border: 1px solid #cbd5e1;
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
    }}
    .btn-reset:hover {{
      background-color: #e2e8f0;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="badge">Artefact EOM Agent &bull; Étape 1</div>
      <h1>Antichambre de Cadrage</h1>
      <p>Client : <strong>{client}</strong> &bull; Lead Détecté : <strong>{lead_email}</strong></p>
    </div>

    <form class="content" action="/antichamber/confirm" method="POST" id="antichamber-form">
      <input type="hidden" name="client" value="{client}">
      <input type="hidden" name="lead_email" value="{lead_email}">

      <!-- 1. Ownership Confirmation -->
      <div class="section-title">1. Validation de Responsabilité (Ownership)</div>
      <label class="radio-card">
        <input type="radio" name="action" value="confirm" checked onchange="handleActionChange()">
        <div>
          <strong style="color: #0f172a; font-size: 14px;">✅ Oui, je confirme être le lead / manager de ce périmètre</strong>
        </div>
      </label>
      <label class="radio-card">
        <input type="radio" name="action" value="reassign" onchange="handleActionChange()">
        <div>
          <strong style="color: #0f172a; font-size: 14px;">🔄 Non, réassigner à un autre lead</strong>
        </div>
      </label>
      <div id="reassign-block" style="display: none; margin: 10px 0 16px 26px;">
        <label style="font-size: 13px; font-weight: 600; color: #334155;">Email du nouveau Lead / Manager :</label>
        <input type="email" name="reassign_email" id="reassign_email" class="form-control" placeholder="prenom.nom@artefact.com" style="margin-top: 4px;">
        <div class="helper-text">L'invitation d'Antichambre lui sera automatiquement réadressée.</div>
      </div>

      <label class="radio-card">
        <input type="radio" name="action" value="exclude" onchange="handleActionChange()">
        <div>
          <strong style="color: #0f172a; font-size: 14px;">❌ Exclure ce périmètre (hors champ / régie sans livrable)</strong>
        </div>
      </label>
      <div id="exclude-block" style="display: none; margin: 10px 0 16px 26px;">
        <label style="font-size: 13px; font-weight: 600; color: #334155;">Motif de l'exclusion :</label>
        <input type="text" name="exclude_reason" id="exclude_reason" class="form-control" placeholder="ex: Prestation régie pure sans livrable capitalisable" style="margin-top: 4px;">
      </div>

      <!-- Configurable Fields Container -->
      <div id="config-fields">
        <!-- 2. Missions & Bundling -->
        <div class="section-title" style="margin-top: 26px;">2. Périmètre & Regroupement de Missions (Bundling)</div>
        <p class="helper-text" style="margin-top: 0; margin-bottom: 12px;">
          Sélectionnez les missions à regrouper dans ce débrief. Un seul Google Doc et un One-Pager Slides unifié seront générés.
        </p>

        {mission_cards_html}

        <div class="form-group" style="margin-top: 16px;">
          <label for="custom_project_name">Nom consolidé du projet pour le One-Pager :</label>
          <div style="display: flex; gap: 8px;">
            <input type="text" id="custom_project_name" name="custom_project_name" class="form-control" value="{initial_title}" oninput="handleTitleManualEdit()" required>
            <button type="button" id="btn-reset-title" class="btn-reset" onclick="resetProjectName()" style="display: none;">↺ Nom auto</button>
          </div>
          <div class="helper-text">Titre affiché sur la slide exécutive Google Slides et le Google Doc. Vous pouvez le renommer librement.</div>
        </div>

        <!-- 3. Delegation & Team -->
        <div class="section-title" style="margin-top: 26px;">3. Responsable Débrief & Délégation (Optionnel)</div>
        <div class="form-group">
          <label for="delegate_email">Responsable de la rédaction du débrief (Délégation) :</label>
          <input type="email" id="delegate_email" name="delegate_email" class="form-control" placeholder="ex: senior.consultant@artefact.com">
          <div class="tip-box">
            💡 <strong>Fonctionnement de la délégation :</strong> Si vous renseignez un email, cette personne recevra l'email de kickoff et sera le contact principal du template. <strong>Vous resterez automatiquement en copie (CC)</strong> pour superviser l'avancement et valider la checklist de conformité.
          </div>
        </div>

        <div class="form-group">
          <label for="cc_emails">Emails additionnels en copie (CC) :</label>
          <input type="text" id="cc_emails" name="cc_emails" class="form-control" placeholder="consultant2@artefact.com, partner@artefact.com">
          <div class="helper-text">Adresses séparées par des virgules.</div>
        </div>

        <!-- 4. Existing Folder -->
        <div class="section-title" style="margin-top: 26px;">4. Dossier de Livrables Existant (Optionnel)</div>
        <div class="form-group">
          <label for="existing_folder_url">URL Google Drive existante (Livrables, Slides, Specs) :</label>
          <input type="url" id="existing_folder_url" name="existing_folder_url" class="form-control" placeholder="https://drive.google.com/drive/folders/...">
          <div class="helper-text">Si vous avez déjà un dossier Drive de livrables, l'agent IA en ingérera les documents pour enrichir le One-Pager.</div>
        </div>
      </div>

      <button type="submit" id="submit-btn" class="btn-submit">🚀 Valider le périmètre & Initialiser l'espace EOM</button>
    </form>
  </div>

  <script>
    let isTitleManuallyEdited = false;

    function handleTitleManualEdit() {{
      isTitleManuallyEdited = true;
      document.getElementById('btn-reset-title').style.display = 'inline-block';
    }}

    function resetProjectName() {{
      isTitleManuallyEdited = false;
      document.getElementById('btn-reset-title').style.display = 'none';
      computeAutoTitle();
    }}

    function computeAutoTitle() {{
      if (isTitleManuallyEdited) return;
      const checkedBoxes = document.querySelectorAll('input[name="selected_mission_ids"]:checked');
      const names = [];
      checkedBoxes.forEach(cb => {{
        const n = cb.getAttribute('data-name');
        if (n) names.push(n.trim());
      }});

      const titleInput = document.getElementById('custom_project_name');
      if (names.length === 0) {{
        titleInput.value = "Mission {client}";
      }} else if (names.length === 1) {{
        titleInput.value = names[0];
      }} else {{
        titleInput.value = names.join(" + ");
      }}
    }}

    function handleCheckboxChange() {{
      computeAutoTitle();
    }}

    function handleActionChange() {{
      const action = document.querySelector('input[name="action"]:checked').value;
      const reassignBlock = document.getElementById('reassign-block');
      const excludeBlock = document.getElementById('exclude-block');
      const configFields = document.getElementById('config-fields');
      const submitBtn = document.getElementById('submit-btn');

      if (action === 'confirm') {{
        reassignBlock.style.display = 'none';
        excludeBlock.style.display = 'none';
        configFields.style.opacity = '1';
        configFields.style.pointerEvents = 'auto';
        submitBtn.innerText = '🚀 Valider le périmètre & Initialiser l\'espace EOM';
        submitBtn.style.backgroundColor = '#1a73e8';
      }} else if (action === 'reassign') {{
        reassignBlock.style.display = 'block';
        excludeBlock.style.display = 'none';
        configFields.style.opacity = '0.4';
        configFields.style.pointerEvents = 'none';
        submitBtn.innerText = '🔄 Réassigner l\'Antichambre au Nouveau Lead';
        submitBtn.style.backgroundColor = '#0f172a';
      }} else if (action === 'exclude') {{
        reassignBlock.style.display = 'none';
        excludeBlock.style.display = 'block';
        configFields.style.opacity = '0.4';
        configFields.style.pointerEvents = 'none';
        submitBtn.innerText = '❌ Confirmer l\'Exclusion du Périmètre';
        submitBtn.style.backgroundColor = '#dc2626';
      }}
    }}
  </script>
</body>
</html>
"""


def render_antichamber_confirmation_page(
    client: str,
    project_name: str,
    primary_lead: str,
    lead_email: str,
    cc_list: List[str],
    launch_res: Dict[str, Any],
    selected_ids: List[str]
) -> str:
    """Renders confirmation page after launch from Antichamber."""
    doc_url = launch_res.get("docUrl", "#")
    folder_url = launch_res.get("folderUrl", "#")
    visuals_url = launch_res.get("visualsFolderUrl", "#")
    email_status = launch_res.get("emailStatus", "SENT")

    delegation_info = ""
    if primary_lead != lead_email:
        delegation_info = f"""
        <div style="background-color: #eff6ff; border-left: 4px solid #1a73e8; padding: 12px 16px; border-radius: 4px; margin: 18px 0; font-size: 13px;">
          👤 <strong>Délégation active :</strong> Kickoff envoyé à <strong>{primary_lead}</strong> (Rédacteur).<br>
          Manager en copie (CC) : <strong>{lead_email}</strong>
        </div>
        """

    cc_info = ""
    if cc_list:
        cc_info = f"<p style='font-size: 13px; color: #475569; margin: 4px 0 0 0;'>Emails en copie (CC) : <strong>{', '.join(cc_list)}</strong></p>"

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>EOM Initialisé • {client}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #f8fafc;
      color: #1e293b;
      margin: 0;
      padding: 40px 15px;
      line-height: 1.5;
    }}
    .container {{
      max-width: 650px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 10px;
      border: 1px solid #e2e8f0;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
      overflow: hidden;
    }}
    .header {{
      background-color: #0f172a;
      color: #ffffff;
      padding: 24px 28px;
    }}
    .badge {{
      display: inline-block;
      background-color: #16a34a;
      color: #ffffff;
      font-size: 11px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 4px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 8px;
    }}
    .header h1 {{
      margin: 0;
      font-size: 22px;
      font-weight: 700;
    }}
    .header p {{
      margin: 6px 0 0 0;
      color: #94a3b8;
      font-size: 13px;
    }}
    .content {{
      padding: 28px;
    }}
    .btn {{
      display: block;
      text-align: center;
      padding: 12px 16px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
      transition: opacity 0.2s;
    }}
    .btn-primary {{
      background-color: #1a73e8;
      color: #ffffff;
    }}
    .btn-dark {{
      background-color: #0f172a;
      color: #ffffff;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="badge">✅ Workspace EOM Initialisé</div>
      <h1>Cadrage Validé avec Succès</h1>
      <p>Projet : <strong>{project_name}</strong> &bull; Client : <strong>{client}</strong></p>
    </div>

    <div class="content">
      <p style="font-size: 15px; margin-top: 0;">
        Le cadrage a été confirmé. Les espaces de travail Google Workspace ont été créés et l'email de lancement (kickoff) a été envoyé ({email_status}).
      </p>

      {delegation_info}
      {cc_info}

      <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px 18px; margin: 20px 0;">
        <h4 style="margin: 0 0 10px 0; color: #0f172a; font-size: 14px;">📦 Ressources Initialisées :</h4>
        <table style="width: 100%; border-collapse: separate; border-spacing: 0 8px;">
          <tr>
            <td style="padding-right: 6px; width: 50%;">
              <a href="{doc_url}" target="_blank" class="btn btn-primary">📄 Google Doc Debrief Template &rarr;</a>
            </td>
            <td style="padding-left: 6px; width: 50%;">
              <a href="{folder_url}" target="_blank" class="btn btn-dark">📁 Dossier Drive de Mission &rarr;</a>
            </td>
          </tr>
          <tr>
            <td style="padding-right: 6px; width: 50%;">
              <a href="{visuals_url}" target="_blank" style="display: block; text-align: center; background-color: #f1f5f9; color: #334155; padding: 10px 14px; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 12px; border: 1px solid #cbd5e1;">
                🖼️ Sous-dossier Visuels
              </a>
            </td>
            <td style="padding-left: 6px; width: 50%;">
              <a href="https://docs.google.com/spreadsheets/d/1IDMXRrgiONxaxqB1N-ahRMoiHx4tqfB9vxhSxyhnH7s/edit" target="_blank" style="display: block; text-align: center; background-color: #f1f5f9; color: #334155; padding: 10px 14px; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 12px; border: 1px solid #cbd5e1;">
                📊 Central Status Tracker
              </a>
            </td>
          </tr>
        </table>
      </div>

      <div style="background-color: #f1f5f9; padding: 12px 16px; border-radius: 6px; font-size: 13px; color: #475569;">
        👉 <strong>Prochaine étape :</strong> L'équipe complète les 3 piliers (Challenge, Solution, Results) dans le Google Doc. Dès complétion ou à J-3, les agents généreront automatiquement la slide exécutive Google Slides et l'audit Sheets.
      </div>
    </div>
  </div>
</body>
</html>
"""


def render_antichamber_exclusion_page(client: str, lead_email: str, reason: Optional[str]) -> str:
    """Renders confirmation page after mission exclusion."""
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Périmètre Exclu • {client}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #f8fafc;
      color: #1e293b;
      margin: 0;
      padding: 40px 15px;
    }}
    .container {{
      max-width: 550px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 10px;
      border: 1px solid #e2e8f0;
      padding: 30px;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div style="font-size: 40px; margin-bottom: 12px;">❌</div>
    <h2 style="color: #0f172a; margin-top: 0;">Périmètre Exclu</h2>
    <p style="color: #475569; font-size: 14px;">
      Le périmètre de mission pour <strong>{client}</strong> a été marqué comme exclu par <strong>{lead_email}</strong>.
    </p>
    <div style="background: #f1f5f9; border-radius: 6px; padding: 10px 14px; margin: 18px 0; font-size: 13px; color: #334155; text-align: left;">
      Motif : <em>{reason or 'Non renseigné'}</em>
    </div>
    <p style="font-size: 13px; color: #64748b;">
      Le statut a été consigné dans le Central Pipeline Status Tracker. Aucun livrable ni email ne sera généré.
    </p>
    <a href="https://docs.google.com/spreadsheets/d/1IDMXRrgiONxaxqB1N-ahRMoiHx4tqfB9vxhSxyhnH7s/edit" target="_blank" style="display: inline-block; margin-top: 10px; color: #1a73e8; font-size: 13px; text-decoration: underline;">
      Consulter le Central Tracker &rarr;
    </a>
  </div>
</body>
</html>
"""


def render_antichamber_reassign_page(client: str, original_lead: str, new_lead: str) -> str:
    """Renders confirmation page after reassignment."""
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Périmètre Réassigné • {client}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #f8fafc;
      color: #1e293b;
      margin: 0;
      padding: 40px 15px;
    }}
    .container {{
      max-width: 550px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 10px;
      border: 1px solid #e2e8f0;
      padding: 30px;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div style="font-size: 40px; margin-bottom: 12px;">🔄</div>
    <h2 style="color: #0f172a; margin-top: 0;">Périmètre Réassigné</h2>
    <p style="color: #475569; font-size: 14px;">
      Le périmètre pour <strong>{client}</strong> a été transféré de <strong>{original_lead}</strong> à <strong>{new_lead}</strong>.
    </p>
    <p style="font-size: 13px; color: #64748b;">
      Une notification d'Antichambre avec le lien de cadrage a été envoyée au nouveau lead.
    </p>
    <a href="https://docs.google.com/spreadsheets/d/1IDMXRrgiONxaxqB1N-ahRMoiHx4tqfB9vxhSxyhnH7s/edit" target="_blank" style="display: inline-block; margin-top: 10px; color: #1a73e8; font-size: 13px; text-decoration: underline;">
      Consulter le Central Tracker &rarr;
    </a>
  </div>
</body>
</html>
"""


@app.get("/antichamber", response_class=HTMLResponse)
def api_get_antichamber(
    request: Request,
    client: Optional[str] = Query(None),
    lead_email: Optional[str] = Query(None),
    mission_ids: Optional[str] = Query(None)
):
    """
    Renders the interactive Antichamber Web Portal for the detected lead.
    Queries candidate missions from BigQuery matching client and/or lead_email.
    """
    clean_client = (client or "").strip()
    clean_lead = (lead_email or "").strip()

    candidate_missions = []
    if clean_client:
        candidate_missions = query_upcoming_missions(client_name=clean_client, days_ahead=None, limit=10)
    if not candidate_missions and clean_lead:
        candidate_missions = query_upcoming_missions(lead_email=clean_lead, days_ahead=None, limit=10)

    # Fallback to realistic mock data if offline / no results
    if not candidate_missions:
        display_client = clean_client or "Crédit Agricole"
        candidate_missions = [
            m for m in MOCK_MISSIONS if display_client.lower() in m.get("client_name", "").lower()
        ]
        if not candidate_missions:
            candidate_missions = [{
                "mission_id": "ATF FR-09652",
                "mission_name": f"CATS - CDP - Pilotage {display_client}",
                "client_name": display_client,
                "lead_email": clean_lead or "ayrton.andre@artefact.com",
                "end_date": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            }, {
                "mission_id": "ATF FR-09616",
                "mission_name": f"{display_client} - PMO Transverse",
                "client_name": display_client,
                "lead_email": clean_lead or "ayrton.andre@artefact.com",
                "end_date": (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
            }]

    resolved_client = clean_client or candidate_missions[0].get("client_name", "Artefact")
    resolved_lead = clean_lead or candidate_missions[0].get("lead_email", "ayrton.andre@artefact.com")

    html_content = render_antichamber_page(
        client=resolved_client,
        lead_email=resolved_lead,
        candidate_missions=candidate_missions
    )
    return HTMLResponse(content=html_content)


@app.post("/antichamber/confirm", operation_id="confirm_antichamber")
async def api_confirm_antichamber(request: Request):
    """
    Processes the Antichamber submission from the web portal form or JSON API.
    Handles bundling multiple missions, designating a delegate (with lead in CC),
    and kicking off Step 2 workspace generation.
    """
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
    else:
        form = await request.form()
        data = dict(form)
        if hasattr(form, "getlist"):
            data["selected_mission_ids"] = form.getlist("selected_mission_ids")

    action = str(data.get("action", "confirm")).strip()
    client = str(data.get("client", "Client")).strip()
    lead_email = str(data.get("lead_email", "")).strip()
    delegate_email = str(data.get("delegate_email", "")).strip()
    custom_project_name = str(data.get("custom_project_name", "")).strip() or f"Mission {client}"
    cc_emails_raw = str(data.get("cc_emails", "")).strip()
    existing_folder_url = str(data.get("existing_folder_url", "")).strip()
    reassign_email = str(data.get("reassign_email", "")).strip()
    exclude_reason = str(data.get("exclude_reason", "")).strip()

    raw_selected = data.get("selected_mission_ids", [])
    if isinstance(raw_selected, str):
        selected_ids = [s.strip() for s in raw_selected.split(",") if s.strip()]
    elif isinstance(raw_selected, list):
        selected_ids = [str(s).strip() for s in raw_selected if str(s).strip()]
    else:
        selected_ids = []

    # Handle Exclusion
    if action == "exclude":
        try:
            handle_log_pipeline_status(
                mission_name=f"[{client}] {custom_project_name}",
                status="ANTICHAMBER_EXCLUDED",
                client=client,
                lead_email=lead_email,
                notes=f"Antichambre : périmètre exclu par {lead_email}. Motif : {exclude_reason or 'Hors champ'}"
            )
        except Exception as e:
            print(f"[Tracker Error] Exclusion log: {e}")

        if "application/json" in request.headers.get("accept", ""):
            return {"status": "EXCLUDED", "client": client, "reason": exclude_reason}
        return HTMLResponse(content=render_antichamber_exclusion_page(client, lead_email, exclude_reason))

    # Handle Reassignment
    if action == "reassign":
        if reassign_email and "@" in reassign_email:
            try:
                base_url = str(request.base_url).rstrip("/")
                from urllib.parse import quote_plus
                portal_link = f"{base_url}/antichamber?client={quote_plus(client)}&lead_email={quote_plus(reassign_email)}"
                missions = query_upcoming_missions(client_name=client, days_ahead=None, limit=5)
                handle_send_antichamber_notification(
                    lead_email=reassign_email,
                    client=client,
                    missions=missions,
                    antichamber_url=portal_link
                )
                handle_log_pipeline_status(
                    mission_name=f"[{client}] Antichambre Staging",
                    status="ANTICHAMBER_REASSIGNED",
                    client=client,
                    lead_email=reassign_email,
                    notes=f"Transféré de {lead_email} à {reassign_email}"
                )
            except Exception as e:
                print(f"[Tracker Error] Reassign log/mail: {e}")

        if "application/json" in request.headers.get("accept", ""):
            return {"status": "REASSIGNED", "client": client, "newLeadEmail": reassign_email}
        return HTMLResponse(content=render_antichamber_reassign_page(client, lead_email, reassign_email))

    # Handle Confirmation & Launch
    primary_lead = delegate_email if (delegate_email and "@" in delegate_email) else lead_email
    cc_list: List[str] = []

    # If delegated, lead_email is automatically placed in CC
    if delegate_email and "@" in delegate_email and delegate_email.lower() != lead_email.lower():
        cc_list.append(lead_email)

    # Parse additional CC emails
    if cc_emails_raw:
        for em in cc_emails_raw.replace(";", ",").split(","):
            cleaned = em.strip()
            if "@" in cleaned and cleaned.lower() != primary_lead.lower() and cleaned not in cc_list:
                cc_list.append(cleaned)

    launch_notes = "Antichambre validée."
    if selected_ids:
        launch_notes += f" Missions regroupées: {', '.join(selected_ids)}."
    if primary_lead != lead_email:
        launch_notes += f" Rédacteur désigné: {primary_lead} (Lead {lead_email} en CC)."

    try:
        if existing_folder_url and existing_folder_url.strip():
            base_url = str(request.base_url).rstrip("/")
            launch_res = handle_prefill_debrief_doc(
                folder_raw=existing_folder_url,
                client=client,
                lead_email=primary_lead,
                mission_name=custom_project_name,
                team_emails=cc_list,
                base_service_url=base_url,
                original_lead_email=lead_email if primary_lead != lead_email else None,
                cc_emails=cc_list,
                notes=launch_notes
            )
        else:
            launch_res = handle_launch_mission(
                mission_name=custom_project_name,
                lead_email=primary_lead,
                client=client,
                folder_id=None,
                original_lead_email=lead_email,
                cc_emails=cc_list,
                notes=launch_notes
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to launch mission from Antichamber: {e}")

    if "application/json" in request.headers.get("accept", ""):
        return launch_res

    return HTMLResponse(content=render_antichamber_confirmation_page(
        client=client,
        project_name=custom_project_name,
        primary_lead=primary_lead,
        lead_email=lead_email,
        cc_list=cc_list,
        launch_res=launch_res,
        selected_ids=selected_ids
    ))


@app.post("/antichamber/send-notification", operation_id="send_antichamber_notification")
def api_send_antichamber_notification(req: SendAntichamberNotificationRequest, request: Request):
    """Emails the Antichamber review link to the mission manager with candidate missions."""
    try:
        lead_email = req.get_lead_email()
        client = req.client
        missions = req.missions
        if missions is None:
            missions = query_upcoming_missions(client_name=client, days_ahead=None, limit=10)
            if not missions:
                missions = query_upcoming_missions(lead_email=lead_email, days_ahead=None, limit=10)

        portal_url = req.get_antichamber_url()
        if not portal_url:
            base = str(request.base_url).rstrip("/")
            from urllib.parse import quote_plus
            portal_url = f"{base}/antichamber?client={quote_plus(client)}&lead_email={quote_plus(lead_email)}"

        return handle_send_antichamber_notification(
            lead_email=lead_email,
            client=client,
            missions=missions,
            antichamber_url=portal_url,
            cc_emails=req.get_cc_emails()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def render_debrief_validation_success_page(
    client: str,
    mission_name: str,
    slide_url: str,
    sheet_url: str,
    folder_url: str,
    doc_url: str,
    slides_count: int = 4,
    images_attached: int = 0
) -> str:
    """Renders validation confirmation page after debrief approval and autonomous wrap-up."""
    img_notice = f" ({images_attached} visuels intégrés)" if images_attached > 0 else ""
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Clôture validée • {client}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #f8fafc;
      color: #1e293b;
      margin: 0;
      padding: 40px 15px;
      line-height: 1.5;
    }}
    .container {{
      max-width: 650px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 10px;
      border: 1px solid #e2e8f0;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
      overflow: hidden;
    }}
    .header {{
      background-color: #0f172a;
      color: #ffffff;
      padding: 24px 28px;
    }}
    .badge {{
      display: inline-block;
      background-color: #16a34a;
      color: #ffffff;
      font-size: 11px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 4px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 8px;
    }}
    .header h1 {{
      margin: 0;
      font-size: 22px;
      font-weight: 700;
    }}
    .header p {{
      margin: 6px 0 0 0;
      color: #94a3b8;
      font-size: 13px;
    }}
    .content {{
      padding: 28px;
    }}
    .btn {{
      display: block;
      text-align: center;
      padding: 12px 16px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
      transition: opacity 0.2s;
    }}
    .btn-primary {{
      background-color: #1a73e8;
      color: #ffffff;
    }}
    .btn-dark {{
      background-color: #0f172a;
      color: #ffffff;
    }}
    .btn-secondary {{
      background-color: #f1f5f9;
      color: #1e293b;
      border: 1px solid #cbd5e1;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="badge">Clôture Validée</div>
      <h1>Débrief Approuvé</h1>
      <p>Mission : <strong>{mission_name}</strong> &bull; Client : <strong>{client}</strong></p>
    </div>

    <div class="content">
      <p style="font-size: 15px; margin-top: 0;">
        Le débrief a été validé. La synthèse multi-persona et la checklist d'audit ont été générées dans votre dossier Google Drive.
      </p>

      <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px 18px; margin: 20px 0;">
        <h4 style="margin: 0 0 10px 0; color: #0f172a; font-size: 14px;">Livrables générés :</h4>
        <table style="width: 100%; border-collapse: separate; border-spacing: 0 8px;">
          <tr>
            <td style="padding-right: 6px; width: 50%;">
              <a href="{slide_url}" target="_blank" class="btn btn-primary">📊 Deck Google Slides ({slides_count} slides{img_notice}) &rarr;</a>
            </td>
            <td style="padding-left: 6px; width: 50%;">
              <a href="{sheet_url}" target="_blank" class="btn btn-dark">🛡️ Checklist Audit Google Sheets &rarr;</a>
            </td>
          </tr>
          <tr>
            <td style="padding-right: 6px; width: 50%;">
              <a href="{folder_url}" target="_blank" class="btn btn-secondary">📁 Dossier Drive de la Mission &rarr;</a>
            </td>
            <td style="padding-left: 6px; width: 50%;">
              <a href="{doc_url}" target="_blank" class="btn btn-secondary">📄 Document de Débrief Validé &rarr;</a>
            </td>
          </tr>
        </table>
      </div>

      <div style="background-color: #f1f5f9; padding: 12px 16px; border-radius: 6px; font-size: 13px; color: #475569;">
        L'email de notification finale a été envoyé avec l'ensemble des liens vers vos livrables. Le statut a été mis à jour dans le Central Pipeline Status Tracker (MISSION_WRAPPED_UP).
      </div>
    </div>
  </div>
</body>
</html>
"""


@app.get("/debrief/validate", operation_id="validate_debrief_get")
async def api_validate_debrief_get(
    request: Request,
    folder_id: str = Query(..., description="Mission folder ID or URL"),
    doc_id: Optional[str] = Query(None, description="Debrief document ID"),
    client: Optional[str] = Query(None, description="Client name"),
    lead_email: Optional[str] = Query(None, description="Lead consultant email"),
    mission_name: Optional[str] = Query(None, description="Mission name")
):
    """
    1-Click Validation endpoint triggered from email CTA or Google Doc link.
    Autonomously executes wrapup pipeline: Slides generation (4 personae), Audit sheet,
    Central Tracker update (MISSION_WRAPPED_UP), and notification email.
    """
    try:
        wrapup_res = handle_wrapup_mission(
            folder_raw=folder_id,
            mission_name=mission_name,
            client=client,
            lead_email=lead_email,
            doc_id=doc_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Échec de la clôture de mission : {e}")

    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return wrapup_res

    return HTMLResponse(content=render_debrief_validation_success_page(
        client=wrapup_res.get("client", client or "Client"),
        mission_name=wrapup_res.get("missionName", mission_name or "Mission"),
        slide_url=wrapup_res.get("slideUrl", ""),
        sheet_url=wrapup_res.get("sheetUrl", ""),
        folder_url=wrapup_res.get("folderUrl", ""),
        doc_url=wrapup_res.get("docUrl", ""),
        slides_count=wrapup_res.get("slidesCount", 4),
        images_attached=wrapup_res.get("imagesAttached", 0)
    ))


@app.post("/debrief/validate", operation_id="validate_debrief_post")
def api_validate_debrief_post(req: ValidateDebriefRequest):
    """
    API endpoint to trigger autonomous wrap-up after consultant debrief review.
    """
    try:
        return handle_wrapup_mission(
            folder_raw=req.get_folder_id(),
            mission_name=req.get_mission_name(),
            client=req.client,
            lead_email=req.get_lead_email(),
            doc_id=req.get_doc_id(),
            cc_emails=req.get_cc_emails()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/debrief/prefill", operation_id="prefill_debrief_doc")
def api_prefill_debrief_doc(req: PrefillDebriefRequest, request: Request):
    """
    API endpoint to analyze Drive folder, detect visuals, synthesize Challenge/Solution/Results,
    and create or update the Google Doc with an AI-prefilled debrief and validation CTA.
    """
    try:
        base_service_url = str(request.base_url).rstrip("/")
        return handle_prefill_debrief_doc(
            folder_raw=req.get_folder_id(),
            client=req.client,
            lead_email=req.get_lead_email(),
            mission_name=req.get_mission_name(),
            team_emails=req.get_team_emails(),
            deadline_date=req.get_deadline_date(),
            industry=req.industry,
            base_service_url=base_service_url,
            prefilled_payload=req.get_prefilled_payload(),
            original_lead_email=req.get_original_lead_email(),
            cc_emails=req.get_cc_emails(),
            notes=req.notes
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/mission/wrapup", operation_id="wrapup_mission")
def api_wrapup_mission(req: WrapupMissionRequest):
    """
    API endpoint to autonomously execute the full end-of-mission wrapup pipeline:
    4-persona Slides, Audit Sheet, Tracker update, and final delivery email.
    """
    try:
        return handle_wrapup_mission(
            folder_raw=req.get_folder_id(),
            mission_name=req.get_mission_name(),
            client=req.client,
            lead_email=req.get_lead_email(),
            doc_id=req.get_doc_id(),
            persona_cards=req.get_persona_cards(),
            persona_images=req.get_persona_images(),
            audit_records=req.get_audit_records(),
            industry=req.industry,
            cc_emails=req.get_cc_emails()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
