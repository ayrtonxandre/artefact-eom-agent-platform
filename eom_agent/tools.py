"""
Google Workspace Tools for Artefact EOM Multi-Agent System.
Wraps Google Drive, Slides, Sheets, and Gmail operations.
"""
import os
import sys
from typing import Dict, Any, List, Optional

from .workspace_service import (
    handle_launch_mission,
    check_debrief_doc_completion,
    handle_send_reminder,
    scan_and_send_reminders,
    handle_extract_documents,
    handle_generate_slide,
    handle_create_audit_sheet,
    handle_send_notification,
    handle_log_pipeline_status
)
from .bigquery_service import (
    query_ended_missions,
    query_mission_financials,
    query_upcoming_missions,
    detect_and_launch_upcoming_missions
)

def detect_upcoming_missions(
    days_ahead: Optional[int] = 7,
    target_date: Optional[str] = None,
    client_name: Optional[str] = None,
    lead_email: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Step 1 in Artefact Target EOM Process: Queries BigQuery (mart_ext_eom_chat_missions)
    to detect active client missions ending at J-7 (or on a target_date).
    
    Args:
        days_ahead: Number of days ahead to scan (default 7 for J-7 kickoff).
        target_date: Optional specific end date formatted as 'YYYY-MM-DD'.
        client_name: Optional substring filter for client name (e.g. 'Crédit Agricole', 'Clariane').
        lead_email: Optional filter for a specific mission lead email.
        limit: Max number of records to retrieve (default 50).
        
    Returns:
        A list of mission records containing mission_id, mission_name, client_name, industry, lead_email, and end_date.
    """
    return query_upcoming_missions(
        days_ahead=days_ahead if not target_date else None,
        target_date=target_date,
        client_name=client_name,
        lead_email=lead_email,
        limit=limit
    )


def orchestrate_eom_detection_and_launch(
    days_ahead: int = 7,
    target_date: Optional[str] = None,
    client_name: Optional[str] = None,
    auto_launch: bool = True,
    dry_run: bool = False,
    override_lead_email: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Autonomous Pipeline Orchestrator: Chains Step 1 (BigQuery Detection) into Step 2 (Kickoff Launch).
    Scans BigQuery for missions ending at J-7, checks the Central Status Tracker for existing entries,
    and automatically launches new missions (creating Drive folders, debrief doc, sending kickoff email, and logging status).
    
    Args:
        days_ahead: Days horizon for detection (default 7).
        target_date: Optional exact date 'YYYY-MM-DD'.
        client_name: Optional client filter.
        auto_launch: If True, launches detected missions; if False, returns preview candidates.
        dry_run: If True, simulates launch without creating Google Drive files or sending emails.
        override_lead_email: Optional email to redirect kickoff notifications during testing (e.g. user email).
        limit: Max number of missions to process in one execution run.
        
    Returns:
        Summary dict containing detection criteria, total detected, launched count, skipped count, and mission details.
    """
    return detect_and_launch_upcoming_missions(
        days_ahead=days_ahead,
        target_date=target_date,
        client_name=client_name,
        auto_launch=auto_launch,
        dry_run=dry_run,
        override_lead_email=override_lead_email,
        limit=limit
    )


def fetch_ended_missions(target_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Queries BigQuery in project global-finance-dashboard to retrieve all missions ending on target_date.
    
    Args:
        target_date: Date string formatted as 'YYYY-MM-DD'. If omitted, defaults to today.
        
    Returns:
        A list of mission records containing mission_id, mission_name, lead_email, drive_folder_url, and financials.
    """
    return query_ended_missions(target_date)


def fetch_mission_financials(mission_name: str) -> Dict[str, Any]:
    """
    Queries BigQuery to fetch financial KPIs (budget sold, days delivered, margin) for a specific mission.
    
    Args:
        mission_name: The name or ID of the mission.
        
    Returns:
        A dictionary containing financial KPIs to enrich executive slides.
    """
    return query_mission_financials(mission_name) or {}

def launch_mission_kickoff(
    mission_name: str,
    lead_email: str,
    client: Optional[str] = None,
    team_emails: Optional[List[str]] = None,
    folder_id: Optional[str] = None,
    parent_folder_id: Optional[str] = None,
    deadline_date: Optional[str] = None,
    industry: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Step 2 in Artefact Target EOM Process: Initializes mission workspace and dispatches kickoff email.
    Creates or locates the mission workspace folder, initializes the structured 3-section Debrief Google Doc
    (Challenge, Solution, Results), creates the Visuals subfolder, sends the launch email to the mission manager
    and team, and records status LAUNCHED in the Central Status Tracker.
    
    Args:
        mission_name: Name of the mission (e.g. Clariane, TotalEnergies).
        lead_email: Email address of the mission delivery manager.
        client: Client company name.
        team_emails: List of project team member email addresses (informed / CC).
        folder_id: Optional existing Google Drive mission folder ID.
        parent_folder_id: Optional parent container ID in which to create the mission workspace folder.
        deadline_date: Optional target completion date string (e.g. '28/10/2026'). Defaults to J-7.
        industry: Optional client industry sector (e.g. 'Bank', 'Pharma', 'Luxury & Beauty').
        
    Returns:
        A dictionary with status, folderId, folderUrl, docId, docUrl, visualsFolderUrl, and emailStatus.
    """
    return handle_launch_mission(
        mission_name=mission_name,
        lead_email=lead_email,
        client=client,
        team_emails=team_emails,
        folder_id=folder_id,
        parent_folder_id=parent_folder_id,
        deadline_date=deadline_date,
        industry=industry,
    )


def check_mission_debrief_status(doc_id_or_folder_id: str) -> Dict[str, Any]:
    """
    Step 3 in Artefact Target EOM Process: Inspects a mission Google Doc (or mission Drive folder)
    to verify completion of the 3-pillar debrief (Challenge, Solution, Results).
    Detects whether template placeholder text has been replaced with substantive content.
    
    Args:
        doc_id_or_folder_id: Google Doc ID, Google Drive folder ID, or full web URL.
        
    Returns:
        Dictionary with docId, docName, isCompleted (bool), completionRate (float 0.0 to 1.0),
        completedSections (list), missingSections (list), and section details.
    """
    return check_debrief_doc_completion(doc_id_or_folder_id)


def send_mission_reminder(
    mission_name: str,
    lead_email: str,
    client: Optional[str] = None,
    doc_id: Optional[str] = None,
    folder_id: Optional[str] = None,
    days_remaining: int = 3,
    deadline_date: Optional[str] = None,
    override_lead_email: Optional[str] = None,
    dry_run: bool = False,
    industry: Optional[str] = None
) -> Dict[str, Any]:
    """
    Step 3 in Artefact Target EOM Process: Dispatches an automated reminder email (J-3 or J-1)
    to the mission delivery lead if the debrief Google Doc is incomplete.
    If the document is already 100% completed, updates the central tracker to DEBRIEF_COMPLETED and skips email.
    
    Args:
        mission_name: Name of the mission (e.g. Clariane, Crédit Agricole).
        lead_email: Email address of the mission delivery lead.
        client: Client company name.
        doc_id: Optional Google Doc ID of the debrief document.
        folder_id: Optional Google Drive mission workspace folder ID.
        days_remaining: Days until project end (e.g. 3 for J-3, 1 for J-1).
        deadline_date: Optional target completion date string (DD/MM/YYYY).
        override_lead_email: Optional email to redirect notifications during testing (e.g. user email).
        dry_run: If True, simulates reminder dispatch without sending email or modifying tracker.
        industry: Optional client industry sector.
        
    Returns:
        Execution dictionary with status, action, leadEmail, missingSections, completionRate, and emailStatus.
    """
    return handle_send_reminder(
        mission_name=mission_name,
        lead_email=lead_email,
        client=client,
        doc_id=doc_id,
        folder_id=folder_id,
        days_remaining=days_remaining,
        deadline_date=deadline_date,
        override_lead_email=override_lead_email,
        dry_run=dry_run,
        industry=industry
    )


def trigger_eom_reminders(
    days_ahead: Optional[int] = None,
    force_send: bool = False,
    dry_run: bool = False,
    override_lead_email: Optional[str] = None,
    limit: int = 20
) -> Dict[str, Any]:
    """
    Step 3 in Artefact Target EOM Process: Autonomous Batch Reminder Engine.
    Scans the Central Pipeline Status Tracker for all active missions awaiting debrief (status LAUNCHED or REMINDER_J3).
    Evaluates debrief completion in Google Drive, and dispatches J-3 / J-1 reminders for incomplete missions
    while logging updated milestones in the Central Status Tracker sheet.
    
    Args:
        days_ahead: Optional specific day horizon to trigger (e.g. 3 for J-3, 1 for J-1). If omitted, evaluates both.
        force_send: If True, triggers reminder dispatch for active missions regardless of calculated date.
        dry_run: If True, simulates scan and reminder preview without sending emails or updating the tracker.
        override_lead_email: Optional email to redirect notifications during testing (e.g. user email).
        limit: Max number of missions to process in one execution run.
        
    Returns:
        Summary dict containing status, totalChecked, remindersSent, debriefsCompleted, skippedCount, and missions array.
    """
    return scan_and_send_reminders(
        days_ahead=days_ahead,
        force_send=force_send,
        dry_run=dry_run,
        override_lead_email=override_lead_email,
        limit=limit
    )


def extract_folder_documents(folder_id: str) -> Dict[str, Any]:
    """
    Extracts text contents and metadata of documents in a Google Drive mission folder.
    
    Args:
        folder_id: The Google Drive folder ID or full URL of the mission folder.
        
    Returns:
        A dictionary with folderId, missionName, filesCount, files array, and aggregatedContext.
    """
    return handle_extract_documents(folder_id)


def generate_one_pager_slide(
    folder_id: str,
    mission_name: str,
    card_data: Any,
    template_id: Optional[str] = "197zP6K146fFlNSPDrDuHoUiKS9c0KODiypl_u27XWDQ"
) -> Dict[str, Any]:
    """
    Clones the Artefact Master Slide Template and populates the 4 executive debrief cards.
    
    Args:
        folder_id: Google Drive Folder ID where the generated slide should be stored.
        mission_name: Name of the mission (e.g., Clariane, TotalEnergies).
        card_data: 4-card executive content dict or JSON (context, deliverables, businessImpact, recommendations, synthesis).
        template_id: Google Slides Master Template ID.
        
    Returns:
        A dictionary with presentationId, presentationUrl, and title.
    """
    return handle_generate_slide(
        folder_raw=folder_id,
        mission_name=mission_name,
        card=card_data,
        template_id=template_id
    )


def create_audit_sheet(
    folder_id: str,
    mission_name: str,
    audit_records: Any
) -> Dict[str, Any]:
    """
    Creates an interactive Knowledge Audit Google Sheet with checkboxes in the mission folder.
    
    Args:
        folder_id: Google Drive folder ID where the spreadsheet will be saved.
        mission_name: Name of the mission.
        audit_records: List of audit record dicts or JSON array with filename, confidentialityRisk, suggestedTags, and toBeExported.
        
    Returns:
        A dictionary with spreadsheetId, spreadsheetUrl, title, and rowsCount.
    """
    return handle_create_audit_sheet(
        folder_raw=folder_id,
        mission_name=mission_name,
        audit_records=audit_records
    )


def send_lead_notification(
    recipient_email: str,
    mission_name: str,
    slide_url: str,
    sheet_url: str
) -> Dict[str, Any]:
    """
    Dispatches a completion notification email to the mission lead with links to generated artifacts.
    
    Args:
        recipient_email: Email of the mission lead (e.g. ayrton.andre@artefact.com).
        mission_name: Name of the mission.
        slide_url: URL to the generated Google Slides executive deck.
        sheet_url: URL to the generated Google Sheets checklist.
        
    Returns:
        A dictionary with status, recipientEmail, and missionName.
    """
    return handle_send_notification(
        recipient_email=recipient_email,
        mission_name=mission_name,
        slide_url=slide_url,
        sheet_url=sheet_url
    )


def log_pipeline_status(
    mission_name: str,
    status: str,
    client: Optional[str] = None,
    lead_email: Optional[str] = None,
    deck_url: Optional[str] = None,
    audit_url: Optional[str] = None,
    folder_url: Optional[str] = None,
    risk: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Step 7 in Target Process: Records or updates the project lifecycle status in the Central Pipeline Status Tracker spreadsheet.
    
    Args:
        mission_name: Name of the mission (e.g., Clariane, TotalEnergies).
        status: Milestone status (e.g. DOCS_EXTRACTED, DECK_GENERATED, AUDIT_READY, NOTIFIED_LEAD, PUBLISHED).
        client: Client company name.
        lead_email: Email address of the mission delivery lead.
        deck_url: Web URL to the generated Google Slides deck.
        audit_url: Web URL to the generated Google Sheets audit checklist.
        folder_url: Web URL to the Google Drive folder.
        risk: Highest detected confidentiality risk (LOW, MEDIUM, HIGH, CRITICAL).
        notes: Execution log notes or details.
        
    Returns:
        A dictionary with status, action, missionName, pipelineStatus, and trackerId.
    """
    return handle_log_pipeline_status(
        mission_name=mission_name,
        status=status,
        client=client,
        lead_email=lead_email,
        deck_url=deck_url,
        audit_url=audit_url,
        folder_url=folder_url,
        risk=risk,
        notes=notes,
    )
