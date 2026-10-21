"""
Comprehensive Verification Suite for Step 1: BigQuery Detection & Pipeline Trigger.
Target Mart: global-finance-dashboard.marts_ext_eom_chat.mart_ext_eom_chat_missions
Execution Project: global-finance-dashboard
Service Account: eom-chat-ap@privategpt-437907.iam.gserviceaccount.com
"""
import sys
import os
import json
from datetime import date, timedelta

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from eom_agent.bigquery_service import (
    query_upcoming_missions,
    query_mission_by_id_or_name,
    detect_and_launch_upcoming_missions,
    get_bigquery_client,
    DEFAULT_MISSIONS_TABLE
)
from eom_agent.workspace_service import (
    get_sheets_service,
    get_credentials,
    DEFAULT_TRACKER_ID,
    CENTRAL_TRACKER_TAB
)

TEST_OVERRIDE_EMAIL = "ayrton.andre@artefact.com"
TEST_PARENT_FOLDER_ID = "1oqx6AT98K36xUOM2G_UYKBRGMfv_ub-U"

print("=" * 75)
print("🧪 RUNNING STEP 1: BIGQUERY DETECTION & AUTONOMOUS PIPELINE TESTS")
print(f"   Target Table: {DEFAULT_MISSIONS_TABLE}")
print("=" * 75)

# ---------------------------------------------------------------------------
# Test 1: Direct BigQuery Connection & Schema Verification
# ---------------------------------------------------------------------------
print("\n--- Test 1: Direct BigQuery Query & Field Verification ---")
client = get_bigquery_client()
test_query = f"""
    SELECT mission_id, mission_name, client_name, industry, lead_email, end_date
    FROM `{DEFAULT_MISSIONS_TABLE}`
    WHERE lead_email IS NOT NULL AND client_name IS NOT NULL
    LIMIT 3
"""
job = client.query(test_query)
rows = list(job.result())
print(f"✅ BigQuery Connected successfully! Retrieved {len(rows)} sample rows.")
for r in rows:
    print(f" • [{r.mission_id}] {r.client_name} - {r.mission_name} | {r.industry} | {r.lead_email} | {r.end_date}")
assert len(rows) > 0, "Expected at least 1 row from BigQuery"

# ---------------------------------------------------------------------------
# Test 2: Step 1 J-7 Detection Query (days_ahead = 7)
# ---------------------------------------------------------------------------
print("\n--- Test 2: Detect missions ending exactly at J-7 (days_ahead = 7) ---")
j7_missions = query_upcoming_missions(days_ahead=7, limit=10)
print(f"Missions ending at J-7: {len(j7_missions)}")
for m in j7_missions:
    print(f" • [{m['mission_id']}] {m['client_name']} - {m['mission_name']}")
    print(f"   Industry: {m['industry']} | Lead: {m['lead_email']} | End Date: {m['end_date']} (in {m['days_until_end']} days)")

assert isinstance(j7_missions, list), "Expected list of missions"

# ---------------------------------------------------------------------------
# Test 3: Date Range & Client Filtering
# ---------------------------------------------------------------------------
print("\n--- Test 3: Query upcoming missions with client filter 'Crédit Agricole' ---")
ca_missions = query_upcoming_missions(client_name="Crédit Agricole", limit=5)
print(f"Crédit Agricole missions found: {len(ca_missions)}")
for m in ca_missions:
    print(f" • [{m['mission_id']}] {m['client_name']} - {m['mission_name']} | Lead: {m['lead_email']} | End: {m['end_date']}")

assert len(ca_missions) > 0, "Expected to find Crédit Agricole missions"

# ---------------------------------------------------------------------------
# Test 4: Autonomous Step 1 -> Step 2 Orchestrator in Simulation Mode (dry_run=True)
# ---------------------------------------------------------------------------
print("\n--- Test 4: Orchestrator Simulation (dry_run=True, days_ahead=7) ---")
sim_res = detect_and_launch_upcoming_missions(
    days_ahead=7,
    dry_run=True,
    override_lead_email=TEST_OVERRIDE_EMAIL,
    limit=5
)
print("Simulation Result Status:", sim_res["status"])
print(f"Total Detected: {sim_res['total_detected']} | Missions in payload: {len(sim_res['missions'])}")
for item in sim_res["missions"]:
    print(f" • [{item.get('action')}] {item.get('client')} - {item.get('mission_name')}")

assert sim_res["status"] == "COMPLETED"

# ---------------------------------------------------------------------------
# Test 5: Step 1 -> Step 2 End-to-End Execution with Lead Redirection
# ---------------------------------------------------------------------------
print("\n--- Test 5: End-to-End Detection & Launch (Safe Test Mode) ---")
# Launch 1 specific mission (e.g. Crédit Agricole) ending in 7 days, redirecting email to test lead
exec_res = detect_and_launch_upcoming_missions(
    days_ahead=7,
    client_name="Crédit Agricole",
    auto_launch=True,
    dry_run=False,
    override_lead_email=TEST_OVERRIDE_EMAIL,
    parent_folder_id=TEST_PARENT_FOLDER_ID,
    limit=1
)
print("Execution Result Status:", exec_res["status"])
print(f"Launched: {exec_res['launched_count']} | Skipped: {exec_res['skipped_count']}")
for item in exec_res["missions"]:
    print(f" • [{item.get('action')}] {item.get('mission_name')}")
    if item.get("action") == "LAUNCHED":
        print(f"   Folder: {item.get('folderUrl')}")
        print(f"   Debrief Doc: {item.get('docUrl')}")
        print(f"   Email Status: {item.get('emailStatus')}")

# ---------------------------------------------------------------------------
# Test 6: Verify Idempotency on Second Run
# ---------------------------------------------------------------------------
print("\n--- Test 6: Verify Idempotency (Second run skips already launched mission) ---")
idempotency_res = detect_and_launch_upcoming_missions(
    days_ahead=7,
    client_name="Crédit Agricole",
    auto_launch=True,
    dry_run=False,
    override_lead_email=TEST_OVERRIDE_EMAIL,
    parent_folder_id=TEST_PARENT_FOLDER_ID,
    limit=1
)
print(f"Second Run - Launched: {idempotency_res['launched_count']} | Skipped: {idempotency_res['skipped_count']}")
for item in idempotency_res["missions"]:
    print(f" • [{item.get('action')}] {item.get('mission_name')} (Status: {item.get('current_status')})")

assert idempotency_res["skipped_count"] >= 1, "Expected mission to be skipped on second run due to idempotency"

# ---------------------------------------------------------------------------
# Test 7: Verify Central Status Tracker Row
# ---------------------------------------------------------------------------
print("\n--- Test 7: Verify Central Pipeline Status Tracker Spreadsheet ---")
creds = get_credentials()
sheets_svc = get_sheets_service(creds)
tracker_rows = sheets_svc.spreadsheets().values().get(
    spreadsheetId=DEFAULT_TRACKER_ID,
    range=f"'{CENTRAL_TRACKER_TAB}'!A:J"
).execute().get("values", [])

found_entry = False
for r in tracker_rows:
    if "Crédit Agricole" in (r[1] if len(r) > 1 else "") or "Crédit Agricole" in (r[0] if len(r) > 0 else ""):
        found_entry = True
        print(f"Found Tracker Entry:")
        print(f" • Mission: {r[0]}")
        print(f" • Client: {r[1]}")
        print(f" • Lead: {r[2]}")
        print(f" • Status: {r[3]}")
        print(f" • Folder: {r[6]}")
        print(f" • Notes: {r[9] if len(r) > 9 else ''}")
        assert r[3] == "LAUNCHED", f"Expected LAUNCHED status, got {r[3]}"
        break

assert found_entry, "Expected Crédit Agricole entry in Central Tracker"

print("\n" + "=" * 75)
print("🎉 ALL STEP 1 & ORCHESTRATOR TESTS PASSED WITH 100% SUCCESS!")
print("=" * 75)
