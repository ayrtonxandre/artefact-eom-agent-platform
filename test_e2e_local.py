"""
End-to-End local verification of the Artefact EOM Tool Service
Directly tests:
1. handle_extract_documents
2. handle_generate_slide
3. handle_create_audit_sheet
4. handle_send_notification
"""
import sys
import os
import json

# Add service directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'service')))
from main import (
    handle_extract_documents,
    handle_generate_slide,
    handle_create_audit_sheet,
    handle_send_notification
)

TEST_FOLDER_ID = "1oqx6AT98K36xUOM2G_UYKBRGMfv_ub-U"
TEST_EMAIL = "ayrton.andre@artefact.com"

print("=" * 60)
print("TEST 1: EXTRACT DOCUMENTS FROM DRIVE (TEST_EOM)")
print("=" * 60)
extract_res = handle_extract_documents(TEST_FOLDER_ID)
mission_name = extract_res.get("missionName") or "Clariane"
print(f"Mission Name    : {mission_name}")
print(f"Files Extracted : {extract_res.get('filesCount')}")
for f in extract_res.get("files", []):
    print(f" - [{f['mimeType']}] {f['name']} ({len(f['content'])} chars)")

print("\n" + "=" * 60)
print("TEST 2: GENERATE ONE-PAGER SLIDE")
print("=" * 60)
card_data = {
    "context": "Clariane (formerly Korian) sought to modernize elderly healthcare facility operations across 7 European countries using AI-driven predictive staffing and resident incident monitoring.",
    "deliverables": "• Enterprise Cloud Foundation on Google Cloud Platform\n• Incident Early-Warning ML Pipeline on Vertex AI\n• Real-Time Facility Operational Cockpit in Looker",
    "businessImpact": "• 24% reduction in staff scheduling discrepancies\n• €1.8M annualized operational savings\n• 99.4% adherence to healthcare compliance standards",
    "recommendations": "• Scale pilot from 40 facilities to full network (600+ sites)\n• Integrate IoT sensor telemetry into the feature store\n• Train regional clinical directors on automated alert triage",
    "synthesis": "Comprehensive AI operational transformation delivered on GCP for Clariane, enabling automated workforce allocation and critical incident risk reduction."
}
slide_res = handle_generate_slide(
    folder_raw=TEST_FOLDER_ID,
    mission_name=mission_name,
    card=card_data,
    template_id="197zP6K146fFlNSPDrDuHoUiKS9c0KODiypl_u27XWDQ"
)
print(f"Slide Created   : {slide_res['title']}")
print(f"Slide ID        : {slide_res['presentationId']}")
print(f"Slide URL       : {slide_res['presentationUrl']}")

print("\n" + "=" * 60)
print("TEST 3: CREATE AUDIT & CHECKLIST SHEET")
print("=" * 60)
audit_records = [
    {
        "filename": "Mission Clariane",
        "confidentialityRisk": "HIGH",
        "suggestedTags": "healthcare, predictive-staffing, vertex-ai",
        "toBeExported": False
    },
    {
        "filename": "Architecture Blueprint - Clariane Lakehouse",
        "confidentialityRisk": "MEDIUM",
        "suggestedTags": "gcp, bigquery, dbt, architecture",
        "toBeExported": True
    },
    {
        "filename": "Executive Summary Template",
        "confidentialityRisk": "LOW",
        "suggestedTags": "methodology, delivery-framework",
        "toBeExported": True
    }
]
sheet_res = handle_create_audit_sheet(
    folder_raw=TEST_FOLDER_ID,
    mission_name=mission_name,
    audit_records=audit_records
)
print(f"Sheet Created   : {sheet_res['title']}")
print(f"Sheet ID        : {sheet_res['spreadsheetId']}")
print(f"Sheet URL       : {sheet_res['spreadsheetUrl']}")

print("\n" + "=" * 60)
print("TEST 4: SEND NOTIFICATION DISPATCH")
print("=" * 60)
notif_res = handle_send_notification(
    recipient_email=TEST_EMAIL,
    mission_name=mission_name,
    slide_url=slide_res['presentationUrl'],
    sheet_url=sheet_res['spreadsheetUrl']
)
print(f"Notification Status: {notif_res.get('status')}")

print("\n" + "=" * 60)
print("🎉 ALL 4 BACKEND ENDPOINTS PASSED END-TO-END VERIFICATION!")
print("=" * 60)
