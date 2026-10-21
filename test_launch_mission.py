"""
Verification script for Step 2: Mission Launch & Kickoff Email Dispatch.
Tests:
1. Folder and Visuals subfolder initialization.
2. Structured 3-section Debrief Google Doc creation.
3. Branded Kickoff Email dispatch to Lead and Team.
4. Central Pipeline Status Tracker milestone recording (LAUNCHED).
5. Idempotent re-run check (no duplicates).
"""
import os
import sys
import json

# Add workspace to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from eom_agent.workspace_service import (
    handle_launch_mission,
    get_sheets_service,
    get_credentials,
    CENTRAL_TRACKER_TAB,
    DEFAULT_TRACKER_ID,
)

TEST_PARENT_FOLDER_ID = "1oqx6AT98K36xUOM2G_UYKBRGMfv_ub-U"
TEST_MISSION_NAME = "Mission Clariane"
TEST_CLIENT = "Clariane"
TEST_LEAD = "ayrton.andre@artefact.com"

print("=" * 70)
print("RUNNING STEP 2 TEST: LAUNCH MISSION & KICKOFF DISPATCH")
print("=" * 70)

# Run 1: Launch mission
res1 = handle_launch_mission(
    mission_name=TEST_MISSION_NAME,
    client=TEST_CLIENT,
    lead_email=TEST_LEAD,
    team_emails=[TEST_LEAD],
    parent_folder_id=TEST_PARENT_FOLDER_ID,
    deadline_date="28/10/2026",
    notes="EOM Automated Kickoff (Step 2 verification)"
)

print(json.dumps(res1, indent=2))

assert res1["status"] == "LAUNCHED", f"Expected LAUNCHED, got {res1['status']}"
assert res1["folderId"], "Missing folderId"
assert res1["docId"], "Missing docId"
assert res1["visualsFolderId"], "Missing visualsFolderId"
assert res1["emailStatus"] == "SENT", f"Expected emailStatus SENT, got {res1['emailStatus']}"

print("\n" + "=" * 70)
print("RUNNING STEP 2 TEST: IDEMPOTENCY CHECK (RE-RUN)")
print("=" * 70)

# Run 2: Re-run should reuse existing folder, doc, and visuals folder without duplication
res2 = handle_launch_mission(
    mission_name=TEST_MISSION_NAME,
    client=TEST_CLIENT,
    lead_email=TEST_LEAD,
    team_emails=[TEST_LEAD],
    parent_folder_id=TEST_PARENT_FOLDER_ID,
    deadline_date="28/10/2026",
    notes="EOM Automated Kickoff (Step 2 idempotency check)"
)

print(f"Run 1 Folder ID: {res1['folderId']} | Run 2 Folder ID: {res2['folderId']}")
print(f"Run 1 Doc ID   : {res1['docId']} | Run 2 Doc ID   : {res2['docId']}")
print(f"Run 1 Visuals  : {res1['visualsFolderId']} | Run 2 Visuals  : {res2['visualsFolderId']}")

assert res1["folderId"] == res2["folderId"], "Folder ID mismatch on re-run"
assert res1["docId"] == res2["docId"], "Doc ID mismatch on re-run"
assert res1["visualsFolderId"] == res2["visualsFolderId"], "Visuals Folder ID mismatch on re-run"

print("\n" + "=" * 70)
print("VERIFYING CENTRAL PIPELINE STATUS TRACKER ROW")
print("=" * 70)

creds = get_credentials()
sheets_svc = get_sheets_service(creds)
tracker_id = os.environ.get("CENTRAL_TRACKER_ID", DEFAULT_TRACKER_ID)
tracker_res = sheets_svc.spreadsheets().values().get(
    spreadsheetId=tracker_id,
    range=f"'{CENTRAL_TRACKER_TAB}'!A:J"
).execute()

rows = tracker_res.get("values", [])
mission_rows = [r for r in rows if r and r[0].strip().lower() == TEST_MISSION_NAME.lower()]
print(f"Rows found for {TEST_MISSION_NAME}: {len(mission_rows)}")
assert len(mission_rows) == 1, f"Expected strictly 1 row in tracker, got {len(mission_rows)}"
print(f"Tracker Row Content: {mission_rows[0]}")
assert mission_rows[0][3] == "LAUNCHED", f"Expected status LAUNCHED, got {mission_rows[0][3]}"

print("\n" + "=" * 70)
print("ALL STEP 2 CHECKS PASSED PERFECTLY!")
print("=" * 70)
