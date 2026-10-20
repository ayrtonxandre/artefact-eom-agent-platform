"""
Test script for BigQuery Service in Artefact EOM Platform.
Tests deterministic SQL queries and mock fallbacks.
"""
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from eom_agent.bigquery_service import query_ended_missions, query_mission_financials

print("=" * 70)
print("🧪 TESTING BIGQUERY SERVICE (Project DP -> Project GE)")
print("=" * 70)

# 1. Test query_ended_missions
print("\n--- Test 1: Query missions ending on 2026-10-20 ---")
missions = query_ended_missions(target_date="2026-10-20")
print(f"Missions found: {len(missions)}")
for m in missions:
    print(f" • [{m.get('mission_id')}] {m.get('mission_name')} - Client: {m.get('client_name')}")
    print(f"   Lead: {m.get('lead_email')} | Budget: €{m.get('budget_sold_eur', 0):,} | Margin: {int(m.get('margin_rate', 0)*100)}%")
    print(f"   Folder: {m.get('drive_folder_url')}")

# 2. Test query_mission_financials
print("\n--- Test 2: Query financials for specific mission 'Clariane' ---")
fin = query_mission_financials("Clariane")
if fin:
    print(f"Financial record retrieved for: {fin.get('mission_name')}")
    print(f" • Sold Days: {fin.get('days_sold')} | Delivered Days: {fin.get('days_delivered')}")
    print(f" • Budget: €{fin.get('budget_sold_eur', 0):,} | Margin: {int(fin.get('margin_rate', 0)*100)}%")
else:
    print("No financial record found.")

print("\n" + "=" * 70)
print("🎉 BigQuery Service tests executed successfully!")
print("=" * 70)
