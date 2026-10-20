"""
Google Workspace Tools for Artefact EOM Multi-Agent System.
Wraps Google Drive, Slides, Sheets, and Gmail operations.
"""
import os
import sys
from typing import Dict, Any, List, Optional

from .workspace_service import (
    handle_extract_documents,
    handle_generate_slide,
    handle_create_audit_sheet,
    handle_send_notification
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
