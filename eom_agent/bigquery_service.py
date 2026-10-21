"""
BigQuery Service for Artefact EOM Platform.
Implements Step 1: Automated Detection of Upcoming / Ending Missions from BigQuery.
Queries Project DP (`global-finance-dashboard.marts_ext_eom_chat.mart_ext_eom_chat_missions`)
using service account `eom-chat-ap@privategpt-437907.iam.gserviceaccount.com`
with execution billed on `global-finance-dashboard`.
"""
import os
import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional

from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError, PermissionDenied, NotFound

# BigQuery Configuration
# Execution project where roles/bigquery.jobUser is granted:
DEFAULT_PROJECT_ID = os.environ.get("BQ_PROJECT_ID", "global-finance-dashboard")

# Target Mart Table prepared by Artefact Data Platform team:
DEFAULT_MISSIONS_TABLE = os.environ.get(
    "BQ_MISSIONS_TABLE",
    "global-finance-dashboard.marts_ext_eom_chat.mart_ext_eom_chat_missions"
)

# Realistic fallback dataset for testing and local development if offline
MOCK_MISSIONS: List[Dict[str, Any]] = [
    {
        "mission_id": "ATF FR-09616",
        "mission_name": "CA-TS / CA-BD - PMO Transverse",
        "client_name": "Crédit Agricole",
        "industry": "Bank",
        "lead_email": "ayrton.andre@artefact.com",
        "end_date": (date.today() + timedelta(days=7)).strftime("%Y-%m-%d"),
        "days_until_end": 7
    },
    {
        "mission_id": "MIS-2026-CLARIANE",
        "mission_name": "Mission Clariane",
        "client_name": "Clariane",
        "industry": "Care providers",
        "lead_email": "ayrton.andre@artefact.com",
        "end_date": date.today().strftime("%Y-%m-%d"),
        "days_until_end": 0
    }
]


def get_bigquery_client(project_id: Optional[str] = None) -> bigquery.Client:
    """
    Initializes a BigQuery client with execution project set to global-finance-dashboard.
    Prioritizes service_account.json if present, otherwise falls back to ADC.
    """
    target_project = project_id or DEFAULT_PROJECT_ID
    candidates = [
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        os.path.join(os.path.dirname(__file__), "..", "service_account.json"),
        os.path.join(os.path.dirname(__file__), "service_account.json"),
    ]
    sa_path = next((p for p in candidates if p and os.path.exists(p)), None)

    if sa_path:
        return bigquery.Client.from_service_account_json(
            sa_path,
            project=target_project
        )
    return bigquery.Client(project=target_project)


def query_upcoming_missions(
    days_ahead: Optional[int] = 7,
    target_date: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    client_name: Optional[str] = None,
    lead_email: Optional[str] = None,
    exclude_internal: bool = True,
    limit: int = 100,
    force_mock: bool = False
) -> List[Dict[str, Any]]:
    """
    Step 1 Core: Executes parameterized SQL query against mart_ext_eom_chat_missions
    to detect missions ending at J-7 (or within a specified horizon/target date).

    Args:
        days_ahead: Number of days ahead (e.g. 7 for J-7 detection). Used if target_date is not provided.
        target_date: Specific end_date string 'YYYY-MM-DD'.
        date_start: Optional start date string 'YYYY-MM-DD' for range query.
        date_end: Optional end date string 'YYYY-MM-DD' for range query.
        client_name: Substring filter for client name.
        lead_email: Filter for specific lead email.
        exclude_internal: If True, filters out non-client activities (ARTEFACT internal, chapters, timesheets).
        limit: Max number of records to return.
        force_mock: If True, returns mock data without querying BigQuery.

    Returns:
        List of detected mission records with metadata, client, lead, and end_date.
    """
    if force_mock or os.environ.get("MOCK_BQ", "false").lower() in ("1", "true", "yes"):
        print(f"[BigQuery] 🧪 Using mock mission data (days_ahead={days_ahead}, target_date={target_date})")
        return MOCK_MISSIONS

    # Build WHERE conditions and parameters dynamically
    conditions = []
    parameters = []

    if target_date:
        conditions.append("end_date = @target_date")
        parameters.append(bigquery.ScalarQueryParameter("target_date", "DATE", target_date))
    elif date_start and date_end:
        conditions.append("end_date BETWEEN @date_start AND @date_end")
        parameters.append(bigquery.ScalarQueryParameter("date_start", "DATE", date_start))
        parameters.append(bigquery.ScalarQueryParameter("date_end", "DATE", date_end))
    elif days_ahead is not None:
        conditions.append("end_date = DATE_ADD(CURRENT_DATE(), INTERVAL @days_ahead DAY)")
        parameters.append(bigquery.ScalarQueryParameter("days_ahead", "INT64", days_ahead))

    # Basic data cleanliness filters
    conditions.append("lead_email IS NOT NULL")
    conditions.append("end_date IS NOT NULL")

    if exclude_internal:
        conditions.append("client_name IS NOT NULL")
        conditions.append("client_name != 'ARTEFACT'")
        conditions.append("NOT LOWER(mission_name) LIKE 'chapter%'")
        conditions.append("NOT LOWER(mission_name) LIKE 'industry%'")
        conditions.append("NOT LOWER(mission_name) LIKE 'timesheets%'")
        conditions.append("NOT LOWER(mission_name) LIKE 'resource loan%'")

    if client_name:
        conditions.append("LOWER(client_name) LIKE @client_pattern")
        parameters.append(bigquery.ScalarQueryParameter("client_pattern", "STRING", f"%{client_name.strip().lower()}%"))

    if lead_email:
        conditions.append("LOWER(lead_email) = @lead_email")
        parameters.append(bigquery.ScalarQueryParameter("lead_email", "STRING", lead_email.strip().lower()))

    where_clause = " AND ".join(conditions) if conditions else "1 = 1"

    query = f"""
        SELECT 
            mission_id,
            mission_name,
            client_name,
            industry,
            lead_email,
            end_date,
            DATE_DIFF(end_date, CURRENT_DATE(), DAY) as days_until_end
        FROM `{DEFAULT_MISSIONS_TABLE}`
        WHERE {where_clause}
        ORDER BY end_date ASC, client_name ASC, mission_name ASC
        LIMIT {int(limit)}
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=parameters,
        use_legacy_sql=False
    )

    try:
        client = get_bigquery_client()
        print(f"[BigQuery] 🚀 Querying {DEFAULT_MISSIONS_TABLE} (Step 1 Detection)...")
        query_job = client.query(query, job_config=job_config)
        rows = list(query_job.result())
        
        results: List[Dict[str, Any]] = []
        for r in rows:
            end_d = r.get("end_date")
            end_date_str = end_d.strftime("%Y-%m-%d") if isinstance(end_d, (date, datetime)) else str(end_d) if end_d else ""
            results.append({
                "mission_id": r.get("mission_id"),
                "mission_name": r.get("mission_name"),
                "client_name": r.get("client_name"),
                "industry": r.get("industry") or "Consulting & Technology",
                "lead_email": r.get("lead_email"),
                "end_date": end_date_str,
                "days_until_end": r.get("days_until_end")
            })

        print(f"[BigQuery] ✅ Step 1 Detection retrieved {len(results)} mission(s).")
        return results

    except Exception as e:
        print(f"[BigQuery] ⚠️  Query failed: {e}. Falling back to mock dataset.")
        return MOCK_MISSIONS


def query_mission_by_id_or_name(mission_identifier: str, force_mock: bool = False) -> Optional[Dict[str, Any]]:
    """
    Retrieves metadata for a specific mission by mission_id or mission_name.
    """
    if force_mock or os.environ.get("MOCK_BQ", "false").lower() in ("1", "true", "yes"):
        for m in MOCK_MISSIONS:
            if mission_identifier.lower() in m["mission_name"].lower() or mission_identifier.lower() in m["mission_id"].lower():
                return m
        return MOCK_MISSIONS[0]

    query = f"""
        SELECT 
            mission_id,
            mission_name,
            client_name,
            industry,
            lead_email,
            end_date,
            DATE_DIFF(end_date, CURRENT_DATE(), DAY) as days_until_end
        FROM `{DEFAULT_MISSIONS_TABLE}`
        WHERE LOWER(mission_id) = @clean_id 
           OR LOWER(mission_name) LIKE @pattern
        LIMIT 1
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("clean_id", "STRING", mission_identifier.strip().lower()),
            bigquery.ScalarQueryParameter("pattern", "STRING", f"%{mission_identifier.strip().lower()}%")
        ]
    )

    try:
        client = get_bigquery_client()
        query_job = client.query(query, job_config=job_config)
        rows = list(query_job.result())
        if rows:
            r = rows[0]
            end_d = r.get("end_date")
            end_date_str = end_d.strftime("%Y-%m-%d") if isinstance(end_d, (date, datetime)) else str(end_d) if end_d else ""
            return {
                "mission_id": r.get("mission_id"),
                "mission_name": r.get("mission_name"),
                "client_name": r.get("client_name"),
                "industry": r.get("industry") or "Consulting & Technology",
                "lead_email": r.get("lead_email"),
                "end_date": end_date_str,
                "days_until_end": r.get("days_until_end")
            }
    except Exception as e:
        print(f"[BigQuery] Error querying mission by id/name: {e}")

    for m in MOCK_MISSIONS:
        if mission_identifier.lower() in m["mission_name"].lower() or mission_identifier.lower() in m["mission_id"].lower():
            return m
    return None


def detect_and_launch_upcoming_missions(
    days_ahead: int = 7,
    target_date: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    client_name: Optional[str] = None,
    auto_launch: bool = True,
    dry_run: bool = False,
    override_lead_email: Optional[str] = None,
    parent_folder_id: Optional[str] = None,
    tracker_id: Optional[str] = None,
    limit: int = 10,
    force_mock: bool = False
) -> Dict[str, Any]:
    """
    Automated End-to-End Orchestrator: Step 1 (Detection) -> Step 2 (Kickoff Launch).
    
    Workflow:
    1. Queries BigQuery mart_ext_eom_chat_missions for missions ending at J-7 (or target_date / range).
    2. Reads the Central Pipeline Status Tracker spreadsheet to identify existing missions.
    3. For any mission not yet launched:
       - If dry_run is True: simulates and previews the action.
       - If auto_launch is True: executes Step 2:
         * Creates Drive mission folder & '01_Visuals & Diagrams' subfolder.
         * Creates 3-pillar Debrief Google Doc template pre-filled with client & industry context.
         * Dispatches Kickoff Email via Gmail API to lead_email (or override_lead_email).
         * Logs milestone in the Central Status Tracker sheet as LAUNCHED.
    4. Returns a comprehensive execution report.
    """
    # Import workspace service dynamically to avoid circular dependencies
    from .workspace_service import (
        handle_launch_mission,
        get_sheets_service,
        get_credentials,
        CENTRAL_TRACKER_TAB,
        DEFAULT_TRACKER_ID
    )

    target_tracker_id = tracker_id or os.environ.get("CENTRAL_TRACKER_ID", DEFAULT_TRACKER_ID)
    
    # 1. Detect missions from BigQuery
    detected_missions = query_upcoming_missions(
        days_ahead=days_ahead if not (target_date or (date_start and date_end)) else None,
        target_date=target_date,
        date_start=date_start,
        date_end=date_end,
        client_name=client_name,
        limit=limit,
        force_mock=force_mock
    )

    # 2. Fetch existing missions from Central Status Tracker
    existing_tracked_missions: Dict[str, Dict[str, Any]] = {}
    try:
        creds = get_credentials()
        sheets_svc = get_sheets_service(creds)
        res = sheets_svc.spreadsheets().values().get(
            spreadsheetId=target_tracker_id,
            range=f"'{CENTRAL_TRACKER_TAB}'!A:J"
        ).execute()
        rows = res.get("values", [])
        for idx, r in enumerate(rows[1:], start=2): # skip header
            if r and len(r) > 0 and r[0].strip():
                clean_name = r[0].strip().lower()
                existing_tracked_missions[clean_name] = {
                    "row_index": idx,
                    "mission_name": r[0],
                    "client": r[1] if len(r) > 1 else "",
                    "lead_email": r[2] if len(r) > 2 else "",
                    "status": r[3] if len(r) > 3 else "",
                    "folder_url": r[6] if len(r) > 6 else ""
                }
    except Exception as e:
        print(f"[Orchestrator] Warning: could not read tracker rows ({e}). Proceeding carefully.")

    # 3. Process each mission
    results: List[Dict[str, Any]] = []
    launched_count = 0
    skipped_count = 0

    for m in detected_missions:
        m_name = m["mission_name"]
        m_client = m.get("client_name") or "Artefact"
        m_id = m.get("mission_id") or ""
        m_lead = m.get("lead_email") or ""
        m_industry = m.get("industry") or "Consulting & Technology"
        m_end_date = m.get("end_date") or ""

        # Check if already tracked by exact name or containing mission ID
        clean_key = m_name.strip().lower()
        full_key = f"[{m_client}] {m_name}".strip().lower()
        
        is_already_tracked = False
        tracked_info = None
        for k, v in existing_tracked_missions.items():
            if clean_key in k or k in clean_key or full_key in k or (m_id and m_id.lower() in k):
                is_already_tracked = True
                tracked_info = v
                break

        # Convert YYYY-MM-DD end_date to DD/MM/YYYY for deadline display
        deadline_display = m_end_date
        if m_end_date and "-" in m_end_date:
            try:
                dt = datetime.strptime(m_end_date, "%Y-%m-%d")
                deadline_display = dt.strftime("%d/%m/%Y")
            except Exception:
                pass

        if is_already_tracked and tracked_info.get("status") in (
            "LAUNCHED", "IN_PROGRESS", "SLIDE_GENERATED", "AUDIT_CREATED", "NOTIFIED_LEAD", "COMPLETED"
        ):
            skipped_count += 1
            results.append({
                "mission_id": m_id,
                "mission_name": m_name,
                "client": m_client,
                "lead_email": m_lead,
                "action": "SKIPPED_ALREADY_LAUNCHED",
                "current_status": tracked_info.get("status"),
                "folder_url": tracked_info.get("folder_url")
            })
            continue

        if dry_run:
            results.append({
                "mission_id": m_id,
                "mission_name": m_name,
                "client": m_client,
                "lead_email": override_lead_email or m_lead,
                "action": "SIMULATED_READY_TO_LAUNCH",
                "deadline_date": deadline_display,
                "industry": m_industry
            })
            continue

        if auto_launch:
            recipient_lead = override_lead_email or m_lead
            formatted_name = f"[{m_client}] {m_name}"
            
            note_str = f"Step 1 BQ Auto-detected (Mission ID: {m_id})"
            if override_lead_email:
                note_str += f" | Real Lead: {m_lead} (Test redirected)"

            try:
                launch_res = handle_launch_mission(
                    mission_name=formatted_name,
                    client=m_client,
                    industry=m_industry,
                    lead_email=recipient_lead,
                    team_emails=[recipient_lead],
                    parent_folder_id=parent_folder_id,
                    deadline_date=deadline_display,
                    notes=note_str
                )
                launched_count += 1
                results.append({
                    "mission_id": m_id,
                    "mission_name": formatted_name,
                    "client": m_client,
                    "lead_email": recipient_lead,
                    "action": "LAUNCHED",
                    "folderId": launch_res.get("folderId"),
                    "folderUrl": launch_res.get("folderUrl"),
                    "docId": launch_res.get("docId"),
                    "docUrl": launch_res.get("docUrl"),
                    "emailStatus": launch_res.get("emailStatus"),
                    "status": "LAUNCHED"
                })
            except Exception as launch_err:
                results.append({
                    "mission_id": m_id,
                    "mission_name": formatted_name,
                    "client": m_client,
                    "lead_email": recipient_lead,
                    "action": "FAILED",
                    "error": str(launch_err)
                })

    return {
        "status": "COMPLETED",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "detection_criteria": {
            "days_ahead": days_ahead,
            "target_date": target_date,
            "date_start": date_start,
            "date_end": date_end,
            "client_name": client_name
        },
        "total_detected": len(detected_missions),
        "launched_count": launched_count,
        "skipped_count": skipped_count,
        "dry_run": dry_run,
        "missions": results
    }


# Backward-compatibility aliases
def query_ended_missions(target_date: Optional[str] = None, force_mock: bool = False) -> List[Dict[str, Any]]:
    return query_upcoming_missions(target_date=target_date, force_mock=force_mock)

def query_mission_financials(mission_name_or_id: str) -> Optional[Dict[str, Any]]:
    return query_mission_by_id_or_name(mission_name_or_id)
