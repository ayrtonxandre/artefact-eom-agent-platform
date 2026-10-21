"""
Google Workspace Tools for Artefact EOM Multi-Agent System.
Wraps Google Drive, Slides, Sheets, and Gmail operations.
"""
import os
import sys
from typing import Dict, Any, List, Optional

from .workspace_service import (
    handle_launch_mission,
    handle_extract_documents,
    handle_generate_slide,
    handle_create_audit_sheet,
    handle_send_notification,
    handle_log_pipeline_status
)
from .bigquery_service import (
    query_ended_missions,
    query_mission_financials
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
