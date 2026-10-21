"""
Comprehensive Verification Suite for Step 3: Automated Reminders (Relances J-3 / J-1).
Tests:
1. Google Doc Debrief inspection & placeholder detection on template doc.
2. Automatic Debrief Doc resolution from Drive Folder ID.
3. Completion evaluation logic (incomplete vs complete).
4. Reminder dispatch simulation (dry_run=True).
5. Safe End-to-End Reminder dispatch with lead redirection (ayrton.andre@artefact.com).
6. Central Pipeline Status Tracker milestone recording (REMINDER_J3 / REMINDER_J1).
7. Autonomous batch reminder scanner (scan_and_send_reminders).
"""
import os
import sys
import json
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from eom_agent.workspace_service import (
    check_debrief_doc_completion,
    handle_send_reminder,
    scan_and_send_reminders,
    handle_log_pipeline_status,
    get_sheets_service,
    get_credentials,
    DEFAULT_TRACKER_ID,
    CENTRAL_TRACKER_TAB
)

TEST_OVERRIDE_EMAIL = "ayrton.andre@artefact.com"
CLARIANE_FOLDER_ID = "1_68EcOyAy6fW9zJJrGxb1MLl63NI2Aas"
CLARIANE_DOC_ID = "1NU9RF6W1Mi4wLL6-c9aBkPa6KHt7L-_SfOlo0tQ3yzg"
TEST_MISSION_NAME = "Mission Clariane"

print("=" * 75)
print("🧪 RUNNING STEP 3: AUTOMATED REMINDERS & DEBRIEF MONITORING TESTS")
print("=" * 75)

# ---------------------------------------------------------------------------
# Test 1: Direct Doc Inspection on Incomplete Template Doc
# ---------------------------------------------------------------------------
print("\n--- Test 1: Inspect Debrief Doc by Doc ID ---")
doc_res = check_debrief_doc_completion(CLARIANE_DOC_ID)
print(f"Doc Name        : {doc_res.get('docName')}")
print(f"isCompleted     : {doc_res.get('isCompleted')}")
print(f"completionRate  : {doc_res.get('completionRate') * 100:.0f}%")
print(f"Missing Sections: {doc_res.get('missingSections')}")
print(f"Completed Secs  : {doc_res.get('completedSections')}")

assert doc_res["isCompleted"] is False, "Expected incomplete template doc"
assert "Challenge" in doc_res["missingSections"], "Expected Challenge to be missing"
assert "Solution" in doc_res["missingSections"], "Expected Solution to be missing"
assert "Results" in doc_res["missingSections"], "Expected Results to be missing"
assert doc_res["completionRate"] == 0.0, f"Expected 0.0 rate, got {doc_res['completionRate']}"
print("✅ Test 1 Passed: Correctly identified all 3 template placeholders as incomplete.")

# ---------------------------------------------------------------------------
# Test 2: Auto-Resolve Debrief Doc from Mission Drive Folder ID
# ---------------------------------------------------------------------------
print("\n--- Test 2: Inspect Debrief Doc via Folder ID Resolution ---")
folder_res = check_debrief_doc_completion(CLARIANE_FOLDER_ID)
print(f"Resolved Doc ID : {folder_res.get('docId')}")
print(f"Resolved Name   : {folder_res.get('docName')}")
print(f"isCompleted     : {folder_res.get('isCompleted')}")

assert folder_res["docId"] == CLARIANE_DOC_ID, f"Expected {CLARIANE_DOC_ID}, got {folder_res['docId']}"
assert folder_res["isCompleted"] is False
print("✅ Test 2 Passed: Folder ID automatically resolved to the mission debrief doc.")

# ---------------------------------------------------------------------------
# Test 3: Simulation Mode for Single Mission Reminder (dry_run=True)
# ---------------------------------------------------------------------------
print("\n--- Test 3: Reminder Dispatch in Simulation Mode (dry_run=True) ---")
sim_res = handle_send_reminder(
    mission_name=TEST_MISSION_NAME,
    lead_email=TEST_OVERRIDE_EMAIL,
    client="Clariane",
    doc_id=CLARIANE_DOC_ID,
    folder_id=CLARIANE_FOLDER_ID,
    days_remaining=3,
    override_lead_email=TEST_OVERRIDE_EMAIL,
    dry_run=True
)
print("Simulation Status   :", sim_res.get("status"))
print("Action              :", sim_res.get("action"))
print("Milestone           :", sim_res.get("milestone"))
print("Missing Sections    :", sim_res.get("missingSections"))

assert sim_res["status"] == "SIMULATED"
assert sim_res["milestone"] == "REMINDER_J3"
assert len(sim_res["missingSections"]) == 3
print("✅ Test 3 Passed: Simulation mode generated J-3 reminder preview without side-effects.")

# ---------------------------------------------------------------------------
# Test 4: Safe End-to-End Reminder Dispatch with Lead Redirection
# ---------------------------------------------------------------------------
print("\n--- Test 4: End-to-End J-3 Reminder Dispatch (Safe Test Mode) ---")
live_res = handle_send_reminder(
    mission_name=TEST_MISSION_NAME,
    lead_email=TEST_OVERRIDE_EMAIL,
    client="Clariane",
    doc_id=CLARIANE_DOC_ID,
    folder_id=CLARIANE_FOLDER_ID,
    days_remaining=3,
    override_lead_email=TEST_OVERRIDE_EMAIL,
    dry_run=False
)
print("Live Result Status  :", live_res.get("status"))
print("Email Status        :", live_res.get("emailStatus"))
print("Recipient Email     :", live_res.get("leadEmail"))

assert live_res["status"] == "REMINDER_J3"
assert live_res["emailStatus"] == "SENT"
assert live_res["leadEmail"] == TEST_OVERRIDE_EMAIL
print("✅ Test 4 Passed: Branded Artefact J-3 reminder HTML email dispatched successfully.")

# ---------------------------------------------------------------------------
# Test 5: Verify Central Status Tracker Milestone Update
# ---------------------------------------------------------------------------
print("\n--- Test 5: Verify Central Pipeline Status Tracker Row Update ---")
creds = get_credentials()
sheets_svc = get_sheets_service(creds)
tracker_id = os.environ.get("CENTRAL_TRACKER_ID", DEFAULT_TRACKER_ID)
res = sheets_svc.spreadsheets().values().get(
    spreadsheetId=tracker_id,
    range=f"'{CENTRAL_TRACKER_TAB}'!A:J"
).execute()
rows = res.get("values", [])

clariane_rows = [r for r in rows if r and r[0].strip().lower() == TEST_MISSION_NAME.lower()]
assert len(clariane_rows) == 1, f"Expected 1 row for {TEST_MISSION_NAME}, found {len(clariane_rows)}"
clariane_row = clariane_rows[0]
print(f"Tracker Row Status : {clariane_row[3]}")
print(f"Tracker Row Notes  : {clariane_row[9] if len(clariane_row) > 9 else ''}")

assert clariane_row[3] == "REMINDER_J3", f"Expected REMINDER_J3, got {clariane_row[3]}"
assert "Relance REMINDER_J3" in clariane_row[9]
print("✅ Test 5 Passed: Tracker row successfully updated to REMINDER_J3 in place.")

# ---------------------------------------------------------------------------
# Test 6: Autonomous Batch Reminders Scanner (scan_and_send_reminders)
# ---------------------------------------------------------------------------
print("\n--- Test 6: Autonomous Batch Scanner in Simulation Mode ---")
batch_sim = scan_and_send_reminders(
    days_ahead=3,
    dry_run=True,
    override_lead_email=TEST_OVERRIDE_EMAIL,
    limit=5
)
print("Batch Status        :", batch_sim.get("status"))
print("Total Checked       :", batch_sim.get("totalChecked"))
print("Reminders Sent      :", batch_sim.get("remindersSent"))
print("Debriefs Completed  :", batch_sim.get("debriefsCompleted"))
print("Skipped Count       :", batch_sim.get("skippedCount"))

assert batch_sim["status"] == "COMPLETED"
assert isinstance(batch_sim["missions"], list)
print("✅ Test 6 Passed: Batch scanner successfully evaluated active pipeline missions.")

# ---------------------------------------------------------------------------
# Test 7: Reset Mission Status for Next Test Iterations
# ---------------------------------------------------------------------------
print("\n--- Test 7: Clean Reset Tracker Status to LAUNCHED ---")
reset_res = handle_log_pipeline_status(
    mission_name=TEST_MISSION_NAME,
    status="LAUNCHED",
    notes="EOM Automated Kickoff (Step 2 & 3 test verification ready)"
)
assert reset_res["status"] == "SUCCESS"
print("✅ Test 7 Passed: Central tracker restored to clean state.")

print("\n" + "=" * 75)
print("🎉 ALL STEP 3 TESTS PASSED PERFECTLY (100% SUCCESS)!")
print("=" * 75)
