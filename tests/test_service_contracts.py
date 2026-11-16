"""
Offline Unit and Contract Tests for EOM Agent Platform.
Verifies OpenAPI models, Pydantic schemas, URL parsing, security exemption logic,
and HTML templates without requiring GCP credentials or network access.
"""
import sys
import os
import unittest

# Ensure repo root and service/ are in sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
SERVICE_DIR = os.path.join(REPO_ROOT, "service")
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

# Guard against Anaconda OpenSSL mismatch
if "oauth2client" not in sys.modules:
    sys.modules["oauth2client"] = None

from service.main import (
    app,
    LaunchMissionRequest,
    SendAntichamberNotificationRequest,
    DetectMissionsRequest,
    DetectAndLaunchRequest,
    CheckDebriefStatusRequest,
    SendReminderRequest,
    ExtractDocumentsRequest,
    GenerateSlideRequest,
    CreateAuditSheetRequest,
    SendNotificationRequest,
    LogPipelineStatusRequest,
)
from eom_agent.workspace_service import (
    parse_folder_id,
    format_card_text,
    is_dispatch_security_exempt,
    build_debrief_doc_html,
    build_kickoff_email_html,
    build_antichamber_email_html,
    build_reminder_email_html,
    build_completed_email_html,
    sanitize_referential_text,
    sanitize_mission_name_for_referential,
    extract_persona_quadrants,
    infer_mission_metadata,
    build_persona_slide_update_requests,
    DEFAULT_MASTER_SLIDE_TEMPLATE_ID,
    PERSONA_CONFIGS,
)


class TestPydanticContracts(unittest.TestCase):
    """Verifies dual naming conventions (camelCase & snake_case) and schema integrity."""

    def test_launch_mission_request_camel_and_snake(self):
        # Test camelCase (OpenAPI style)
        req_camel = LaunchMissionRequest(
            missionName="Project Titan",
            leadEmail="lead@artefact.com",
            folderId="12345abcdef",
            deadlineDate="2026-11-15",
            ccEmails=["pm@artefact.com"],
        )
        self.assertEqual(req_camel.get_mission_name(), "Project Titan")
        self.assertEqual(req_camel.get_lead_email(), "lead@artefact.com")
        self.assertEqual(req_camel.get_folder_id(), "12345abcdef")
        self.assertEqual(req_camel.get_deadline_date(), "2026-11-15")
        self.assertEqual(req_camel.get_cc_emails(), ["pm@artefact.com"])

        # Test snake_case (Python style)
        req_snake = LaunchMissionRequest(
            mission_name="Project Titan Snake",
            lead_email="lead2@artefact.com",
            folder_id="67890uvwxyz",
            deadline_date="2026-12-01",
            cc_emails=["pm2@artefact.com"],
        )
        self.assertEqual(req_snake.get_mission_name(), "Project Titan Snake")
        self.assertEqual(req_snake.get_lead_email(), "lead2@artefact.com")
        self.assertEqual(req_snake.get_folder_id(), "67890uvwxyz")
        self.assertEqual(req_snake.get_deadline_date(), "2026-12-01")

    def test_launch_mission_request_missing_required(self):
        req = LaunchMissionRequest()
        with self.assertRaises(ValueError):
            req.get_mission_name()
        with self.assertRaises(ValueError):
            req.get_lead_email()

    def test_antichamber_notification_request(self):
        req = SendAntichamberNotificationRequest(
            client="Danone",
            leadEmail="lead@artefact.com",
            antichamberUrl="https://eom.artefact.com/antichamber?token=xyz",
            ccEmails=["director@artefact.com"]
        )
        self.assertEqual(req.client, "Danone")
        self.assertEqual(req.get_lead_email(), "lead@artefact.com")
        self.assertEqual(req.get_antichamber_url(), "https://eom.artefact.com/antichamber?token=xyz")
        self.assertEqual(req.get_cc_emails(), ["director@artefact.com"])

    def test_detect_missions_request_defaults(self):
        req = DetectMissionsRequest()
        self.assertEqual(req.get_days_ahead(), 7)

        req_custom = DetectMissionsRequest(daysAhead=14)
        self.assertEqual(req_custom.get_days_ahead(), 14)

    def test_send_notification_request_camel_and_snake(self):
        req_camel = SendNotificationRequest(
            recipientEmail="antoine.de-pommereau@artefact.com",
            missionName="Monitoring Platform for Agent Managers",
            slideUrl="https://docs.google.com/presentation/d/deck123/edit",
            sheetUrl="https://docs.google.com/spreadsheets/d/sheet123/edit",
            ccEmails=["clemence.dhemery@artefact.com", "claire.sauvage@artefact.com"]
        )
        self.assertEqual(req_camel.get_recipient_email(), "antoine.de-pommereau@artefact.com")
        self.assertEqual(req_camel.get_mission_name(), "Monitoring Platform for Agent Managers")
        self.assertEqual(req_camel.get_cc_emails(), ["clemence.dhemery@artefact.com", "claire.sauvage@artefact.com"])

        req_snake = SendNotificationRequest(
            recipient_email="antoine.de-pommereau@artefact.com",
            mission_name="Monitoring Platform for Agent Managers",
            slide_url="https://docs.google.com/presentation/d/deck123/edit",
            sheet_url="https://docs.google.com/spreadsheets/d/sheet123/edit",
            cc_emails=["ayrton.andre@artefact.com"]
        )
        self.assertEqual(req_snake.get_recipient_email(), "antoine.de-pommereau@artefact.com")
        self.assertEqual(req_snake.get_cc_emails(), ["ayrton.andre@artefact.com"])


class TestWorkspaceHelpers(unittest.TestCase):
    """Verifies folder ID parsing, text formatting, and security whitelists."""

    def test_parse_folder_id_formats(self):
        raw_id = "1oqx6AT98K36xUOM2G_UYKBRGMfv_ub-U"
        # 1. Raw ID string
        self.assertEqual(parse_folder_id(raw_id), raw_id)
        # 2. Standard Google Drive URL
        url1 = f"https://drive.google.com/drive/folders/{raw_id}"
        self.assertEqual(parse_folder_id(url1), raw_id)
        # 3. User subfolder URL
        url2 = f"https://drive.google.com/drive/u/0/folders/{raw_id}?usp=sharing"
        self.assertEqual(parse_folder_id(url2), raw_id)

    def test_format_card_text(self):
        self.assertEqual(format_card_text("Simple String"), "Simple String")
        self.assertEqual(format_card_text(["Bullet 1", "Bullet 2"]), "• Bullet 1\n• Bullet 2")
        self.assertEqual(format_card_text(None), "N/A")

    def test_is_dispatch_security_exempt(self):
        # Whitelisted missions should bypass redirection
        self.assertTrue(is_dispatch_security_exempt("Monitoring Platform for Agent Managers"))
        self.assertTrue(is_dispatch_security_exempt("ATF-FR-26-022802 - Clariane Migration"))
        # Non-whitelisted missions should not be exempt
        self.assertFalse(is_dispatch_security_exempt("Retail AI Assistant - Carrefour"))
        self.assertFalse(is_dispatch_security_exempt(None))
        self.assertFalse(is_dispatch_security_exempt(""))


class TestHTMLTemplates(unittest.TestCase):
    """Verifies that debrief and notification HTML templates render expected anchors and content."""

    def test_build_debrief_doc_html(self):
        html = build_debrief_doc_html(
            mission_name="AI Factory 2026",
            client="Sanofi",
            lead_email="lead@artefact.com",
            team_emails=["consultant@artefact.com"],
            deadline_str="2026-11-20",
            visuals_url="https://drive.google.com/drive/folders/vis123",
            industry="Healthcare"
        )
        self.assertIn("AI Factory 2026", html)
        self.assertIn("Sanofi", html)
        self.assertIn("lead@artefact.com", html)
        self.assertIn("2026-11-20", html)
        self.assertIn("1. Challenge (Contexte & Problématique Client)", html)
        self.assertIn("2. Solution (Livrables & Architecture Déployée)", html)
        self.assertIn("3. Results & Impact", html)

    def test_build_kickoff_email_html(self):
        html = build_kickoff_email_html(
            mission_name="CDP Deployment",
            client="L'Oréal",
            lead_email="lead@artefact.com",
            team_emails=["dev@artefact.com"],
            deadline_str="2026-11-25",
            doc_url="https://docs.google.com/document/d/doc123/edit",
            visuals_url="https://drive.google.com/drive/folders/vis123",
            folder_url="https://drive.google.com/drive/folders/fld123",
            folder_name="[L'Oréal] CDP Deployment - EOM Hub"
        )
        self.assertIn("CDP Deployment", html)
        self.assertIn("L'Oréal", html)
        self.assertIn("https://docs.google.com/document/d/doc123/edit", html)
        self.assertIn("https://drive.google.com/drive/folders/fld123", html)

    def test_build_antichamber_email_html(self):
        missions = [{"mission_id": "M1", "mission_name": "Test Mission 1"}]
        html = build_antichamber_email_html(
            client="TotalEnergies",
            lead_email="lead@artefact.com",
            missions=missions,
            antichamber_url="https://antichamber.local/test"
        )
        self.assertIn("TotalEnergies", html)
        self.assertIn("https://antichamber.local/test", html)
        self.assertIn("Test Mission 1", html)

    def test_build_completed_email_html(self):
        html = build_completed_email_html(
            mission_name="GenAI Governance",
            slide_url="https://docs.google.com/presentation/d/deck123/edit",
            sheet_url="https://docs.google.com/spreadsheets/d/sheet123/edit",
            client="BNP Paribas"
        )
        self.assertIn("GenAI Governance", html)
        self.assertIn("BNP Paribas", html)
        self.assertIn("https://docs.google.com/presentation/d/deck123/edit", html)
        self.assertIn("https://docs.google.com/spreadsheets/d/sheet123/edit", html)


class TestMultiPersonaSlideGeneration(unittest.TestCase):
    """Verifies multi-persona slide request generation, schema contracts, and referential sanitization."""

    def test_generate_slide_request_multi_persona(self):
        req = GenerateSlideRequest(
            folderId="folder_123",
            missionName="[Ferrero] Agent Monitoring",
            client="Ferrero",
            personae=["executive", "technical", "knowledge", "referential"],
            cardData={"executive": {"context": "Exec context"}}
        )
        self.assertEqual(req.get_folder_id(), "folder_123")
        self.assertEqual(req.get_mission_name(), "[Ferrero] Agent Monitoring")
        self.assertEqual(req.get_client(), "Ferrero")
        self.assertEqual(req.get_personae(), ["executive", "technical", "knowledge", "referential"])
        self.assertIn("executive", req.get_card_data())

    def test_sanitize_referential_text_strips_client_and_brands(self):
        raw_text = (
            "Ferrero's AI operations deployed on Azure using OpenTelemetry. "
            "Nutella and Kinder brand teams experienced zero downtime with Ferrero guidelines."
        )
        sanitized = sanitize_referential_text(
            text=raw_text,
            client="Ferrero",
            descriptor="Global Tier-1 FMCG Leader",
            brands=["Nutella", "Kinder"]
        )
        # Client name and brands must be purged
        self.assertNotIn("Ferrero", sanitized)
        self.assertNotIn("Nutella", sanitized)
        self.assertNotIn("Kinder", sanitized)

        # Replaced with descriptor and generic brand labels
        self.assertIn("Global Tier-1 FMCG Leader's AI operations", sanitized)
        self.assertIn("Flagship Brand", sanitized)

        # Technical architecture details must be strictly preserved
        self.assertIn("Azure", sanitized)
        self.assertIn("OpenTelemetry", sanitized)

    def test_sanitize_mission_name_for_referential(self):
        # 1. Bracketed client tag
        s1 = sanitize_mission_name_for_referential(
            mission_name="[Ferrero] Monitoring Platform for Agent Managers",
            client="Ferrero"
        )
        self.assertEqual(s1, "Monitoring Platform for Agent Managers")

        # 2. Hyphen prefix
        s2 = sanitize_mission_name_for_referential(
            mission_name="Ferrero - Monitoring Platform for Agent Managers",
            client="Ferrero"
        )
        self.assertEqual(s2, "Monitoring Platform for Agent Managers")

        # 3. Colon prefix
        s3 = sanitize_mission_name_for_referential(
            mission_name="Ferrero: Agent Hub",
            client="Ferrero"
        )
        self.assertEqual(s3, "Agent Hub")

    def test_extract_persona_quadrants_flexible_keys(self):
        # Format 1: Direct card keys
        p1 = {
            "card1": "Context 1",
            "card2": "Deliverables 2",
            "card3": "Impact 3",
            "card4": "Recommendations 4",
            "synthesis": "Synthesis 5"
        }
        res1 = extract_persona_quadrants(p1)
        self.assertEqual(res1["card1"], "Context 1")
        self.assertEqual(res1["card2"], "Deliverables 2")
        self.assertEqual(res1["card3"], "Impact 3")
        self.assertEqual(res1["card4"], "Recommendations 4")
        self.assertEqual(res1["synthesis"], "Synthesis 5")

        # Format 2: Structured title/content dicts
        p2 = {
            "card1": {"title": "Context", "content": "Detailed Context Content"},
            "card2": {"title": "Deliverables", "content": "Detailed Deliverables Content"},
            "card3": {"title": "Metrics", "content": "Detailed Metrics Content"},
            "card4": {"title": "DevOps", "content": "Detailed DevOps Content"},
            "synthesis": "Synthesis Text"
        }
        res2 = extract_persona_quadrants(p2)
        self.assertEqual(res2["card1"], "Detailed Context Content")
        self.assertEqual(res2["card2"], "Detailed Deliverables Content")
        self.assertEqual(res2["card3"], "Detailed Metrics Content")
        self.assertEqual(res2["card4"], "Detailed DevOps Content")

    def test_build_persona_slide_update_requests_scoped_and_themed(self):
        slide_id = "slide_tech_02"
        tech_data = {
            "card1": "Python & OpenTelemetry SDK constraints",
            "card2": "Azure Managed Grafana and Log Analytics Workspace",
            "card3": "P95 latency reduced to 1.8s, 99.9% uptime",
            "card4": "Terraform modules and GitHub Actions CI/CD",
            "synthesis": "Full-stack observability architecture on Azure"
        }
        reqs = build_persona_slide_update_requests(
            slide_id=slide_id,
            persona_key="technical",
            raw_persona_data=tech_data,
            mission_name="[Ferrero] Agent Monitoring",
            today_str="2026-11-06",
            client="Ferrero"
        )
        # All requests must be scoped to slide_id
        for r in reqs:
            self.assertIn("replaceAllText", r)
            self.assertEqual(r["replaceAllText"].get("pageObjectIds"), [slide_id])

        # Title prefix must be TECHNICAL BLUEPRINT:
        title_repl = [r["replaceAllText"]["replaceText"] for r in reqs if r["replaceAllText"]["containsText"]["text"] == "MISSION ONE-PAGER:"]
        self.assertEqual(title_repl, ["TECHNICAL BLUEPRINT:"])

        # Headers must match technical config
        h1 = [r["replaceAllText"]["replaceText"] for r in reqs if r["replaceAllText"]["containsText"]["text"] == "🎯 CONTEXT & CLIENT OBJECTIVES"]
        self.assertEqual(h1, [PERSONA_CONFIGS["technical"]["headers"]["card_1"]])

        # Technical terms must remain uncorrupted
        c2 = [r["replaceAllText"]["replaceText"] for r in reqs if r["replaceAllText"]["containsText"]["text"] == "{{DELIVERABLES}}"]
        self.assertIn("Azure Managed Grafana and Log Analytics Workspace", c2[0])

    def test_build_persona_slide_update_requests_referential_anonymization(self):
        slide_id = "slide_ref_04"
        ref_data = {
            "card1": "Ferrero needed enterprise visibility across its GenAI agent fleet.",
            "card2": "Artefact deployed standardized OpenTelemetry telemetry for Ferrero.",
            "card3": "Achieved -40% MTTR across Ferrero's business operations.",
            "card4": "Proven credentials in enterprise observability for Nutella brand workflows.",
            "synthesis": "Scalable agent governance implemented for Ferrero.",
            "anonymizedClient": "Global Tier-1 FMCG Leader"
        }
        reqs = build_persona_slide_update_requests(
            slide_id=slide_id,
            persona_key="referential",
            raw_persona_data=ref_data,
            mission_name="[Ferrero] Monitoring Platform for Agent Managers",
            today_str="2026-11-06",
            client="Ferrero",
            anonymized_client="Global Tier-1 FMCG Leader"
        )

        # Title prefix must be COMMERCIAL CASE STUDY:
        title_repl = [r["replaceAllText"]["replaceText"] for r in reqs if r["replaceAllText"]["containsText"]["text"] == "MISSION ONE-PAGER:"]
        self.assertEqual(title_repl, ["COMMERCIAL CASE STUDY:"])

        # Mission title replacement must NOT contain Ferrero
        mission_repl = [r["replaceAllText"]["replaceText"] for r in reqs if r["replaceAllText"]["containsText"]["text"] == "{{MISSION_NAME}}"]
        self.assertEqual(mission_repl, ["Monitoring Platform for Agent Managers"])
        self.assertNotIn("Ferrero", mission_repl[0])

        # Verify zero occurrences of 'Ferrero' or 'Nutella' anywhere in replacement texts
        for r in reqs:
            repl_text = r["replaceAllText"]["replaceText"]
            self.assertNotIn("Ferrero", repl_text, f"Referential leakage of client name in: {repl_text}")
            self.assertNotIn("Nutella", repl_text, f"Referential leakage of brand name in: {repl_text}")

        # Verify that descriptor is present
        c1 = [r["replaceAllText"]["replaceText"] for r in reqs if r["replaceAllText"]["containsText"]["text"] == "{{CONTEXT}}"]
        self.assertIn("Global Tier-1 FMCG Leader", c1[0])

    def test_default_master_slide_template_id(self):
        """Verifies that the default master slide template ID is updated to the 2025 Artefact master template."""
        self.assertEqual(DEFAULT_MASTER_SLIDE_TEMPLATE_ID, "1DH-zXzB9CmaYB-p0CyXJDR-gdeJ6gSvylM-76IPfkEY")
        gen_req = GenerateSlideRequest(
            folderId="folder123",
            missionName="Project Alpha"
        )
        self.assertEqual(gen_req.get_template_id(), "1DH-zXzB9CmaYB-p0CyXJDR-gdeJ6gSvylM-76IPfkEY")

    def test_infer_mission_metadata(self):
        """Verifies sector and tech badge inference logic."""
        # Ferrero
        meta_ferrero = infer_mission_metadata(client="Ferrero", mission_name="[Ferrero] Agent Monitoring Platform")
        self.assertEqual(meta_ferrero["industry"], "CPG & Retail")
        self.assertEqual(meta_ferrero["topic"], "GenAI & Ops")
        self.assertEqual(meta_ferrero["tech_stack"], "GCP / Vertex")

        # Clariane
        meta_clariane = infer_mission_metadata(client="Clariane", mission_name="Clariane - Health Data Lake")
        self.assertEqual(meta_clariane["industry"], "Healthcare")

        # Explicit overrides
        meta_custom = infer_mission_metadata(
            client="CustomCorp",
            mission_name="AI Pilot",
            raw_card={"industry": "FinTech", "topic": "Robo-Advisory", "tech_stack": "AWS / Bedrock", "duration": "8 semaines"}
        )
        self.assertEqual(meta_custom["industry"], "FinTech")
        self.assertEqual(meta_custom["topic"], "Robo-Advisory")
        self.assertEqual(meta_custom["tech_stack"], "AWS / Bedrock")
        self.assertEqual(meta_custom["duration"], "8 semaines")

    def test_build_persona_slide_update_requests_2025_master_placeholders(self):
        """Verifies that 2025 Artefact master template placeholders are correctly populated."""
        slide_id = "slide_exec_01"
        exec_data = {
            "card1": "Client wanted centralized AI governance.",
            "card2": "Delivered agent monitoring platform.",
            "card3": "45% reduction in manual triage.",
            "card4": "Scale to North America in Q2.",
            "synthesis": "Comprehensive AI governance delivered."
        }
        reqs = build_persona_slide_update_requests(
            slide_id=slide_id,
            persona_key="executive",
            raw_persona_data=exec_data,
            mission_name="[Ferrero] Monitoring Platform",
            today_str="2026-11-06",
            client="Ferrero",
            industry="CPG & Retail",
            topic="GenAI & Ops",
            tech_stack="GCP / Vertex",
            duration="14 semaines",
            dispositif="1 M, 1 PO, 2 DS, 1 DE"
        )

        placeholders_found = {r["replaceAllText"]["containsText"]["text"]: r["replaceAllText"]["replaceText"] for r in reqs}

        # 2025 Master Placeholders
        self.assertEqual(placeholders_found.get("{{MISSION_TITLE}}"), "EXECUTIVE SUMMARY: [Ferrero] Monitoring Platform")
        self.assertEqual(placeholders_found.get("{{INDUSTRY_TAG}}"), "CPG & Retail")
        self.assertEqual(placeholders_found.get("{{TOPIC_TAG}}"), "GenAI & Ops")
        self.assertEqual(placeholders_found.get("{{CLIENT_TAG}}"), "FERRERO")
        self.assertEqual(placeholders_found.get("{{TECH_TAG}}"), "GCP / Vertex")
        self.assertEqual(placeholders_found.get("{{DURATION_TAG}}"), "14 semaines")
        self.assertEqual(placeholders_found.get("{{DISPOSITIF_TAG}}"), "1 M, 1 PO, 2 DS, 1 DE")
        self.assertEqual(placeholders_found.get("{{CARD_4_HEADER}}"), "💡 STRATEGIC NEXT STEPS & GOVERNANCE")

        # 4 Cards
        self.assertIn("centralized AI governance", placeholders_found.get("{{CONTEXT}}", ""))
        self.assertIn("agent monitoring platform", placeholders_found.get("{{DELIVERABLES}}", ""))
        self.assertIn("45% reduction", placeholders_found.get("{{BUSINESS_IMPACT}}", ""))
        self.assertIn("Scale to North America", placeholders_found.get("{{RECOMMENDATIONS}}", ""))


class TestFastAPIContracts(unittest.TestCase):
    """Verifies that the FastAPI application initializes with valid OpenAPI schemas and endpoints."""

    def test_openapi_schema_structure(self):
        schema = app.openapi()
        self.assertEqual(schema["info"]["title"], "Artefact EOM Workspace Tool Service")
        self.assertEqual(schema["info"]["version"], "1.0.0")

        # Must include all critical endpoints
        paths = schema["paths"]
        expected_endpoints = [
            "/healthz",
            "/missions/detect",
            "/missions/detect-and-launch",
            "/launch-mission",
            "/missions/check-debrief",
            "/send-reminder",
            "/extract-documents",
            "/generate-slide",
            "/create-audit-sheet",
            "/send-notification",
            "/log-pipeline-status",
            "/antichamber",
            "/antichamber/confirm",
            "/antichamber/send-notification"
        ]
        for ep in expected_endpoints:
            self.assertIn(ep, paths, f"Missing critical endpoint: {ep}")

    def test_healthz_route(self):
        from fastapi.testclient import TestClient
        client = TestClient(app)
        res = client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "Artefact EOM Workspace Tool Service")


if __name__ == "__main__":
    unittest.main()
