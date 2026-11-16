import unittest
import re
import sys
import os
from unittest.mock import patch, MagicMock

# Guard against Anaconda OpenSSL mismatch
if "oauth2client" not in sys.modules:
    sys.modules["oauth2client"] = None

from fastapi.testclient import TestClient

from service.main import (
    app,
    ValidateDebriefRequest,
    PrefillDebriefRequest,
    WrapupMissionRequest,
    render_debrief_validation_success_page
)
from eom_agent.workspace_service import (
    build_debrief_doc_html,
    build_kickoff_email_html,
    check_debrief_doc_completion,
    format_html_list_or_paragraphs
)
from eom_agent.tools import (
    prefill_mission_debrief,
    wrapup_mission_deliverables
)
from eom_agent.agent import root_agent

client = TestClient(app)

class TestPrefilledDebriefDocHTML(unittest.TestCase):
    """Verifies debrief HTML generation in blank and AI-prefilled modes."""

    def test_blank_debrief_doc_html(self):
        html = build_debrief_doc_html(
            mission_name="AI Pilot 2026",
            client="Danone",
            lead_email="lead@artefact.com",
            team_emails=["consultant@artefact.com"],
            deadline_str="2026-11-20",
            visuals_url="https://drive.google.com/drive/folders/vis123",
            industry="FMCG"
        )
        self.assertIn("AI Pilot 2026", html)
        self.assertIn("Danone", html)
        self.assertIn("1. Challenge", html)
        self.assertIn("2. Solution", html)
        self.assertIn("3. Results & Impact", html)
        # Should not have prefilled AI banner
        self.assertNotIn("DÉBRIEF PRÉ-REMPLI PAR L'IA", html)
        self.assertNotIn("Validation du Débrief par le Consultant", html)

    def test_prefilled_debrief_doc_html(self):
        prefilled_data = {
            "challenge": ["Challenge 1: Fragmentation", "Challenge 2: Latence"],
            "solution": ["Solution 1: BigQuery", "Solution 2: Vertex AI"],
            "results": ["99.8% disponibilité", "30% économies"]
        }
        detected_visuals = [
            {"name": "arch_gcp.png", "type": "Diagramme Technique", "target_persona": "Slide 2 : Blueprint Technique"},
            {"name": "dashboard_looker.png", "type": "Capture d'écran", "target_persona": "Slide 1 : Exécutif"}
        ]
        persona_preview = {
            "executive": {"title": "👔 Slide 1 : Exécutif", "summary": "Executive summary preview"},
            "technical": {"title": "⚙️ Slide 2 : Technique", "summary": "Technical blueprint preview"},
            "knowledge": {"title": "📚 Slide 3 : Capitalisation", "summary": "Knowledge lessons preview"},
            "referential": {"title": "💼 Slide 4 : Référentiel", "summary": "Referential sanitized preview"}
        }
        validation_url = "https://eom.artefact.com/debrief/validate?folder_id=f123&doc_id=d456"

        html = build_debrief_doc_html(
            mission_name="GenAI Observability",
            client="Ferrero",
            lead_email="ayrton.andre@artefact.com",
            team_emails=["pierre.durand@artefact.com"],
            deadline_str="2026-11-20",
            visuals_url="https://drive.google.com/drive/folders/vis123",
            industry="CPG & Retail",
            prefilled_data=prefilled_data,
            persona_preview=persona_preview,
            detected_visuals=detected_visuals,
            validation_url=validation_url
        )

        # 1. AI banner & validation box
        self.assertIn("DÉBRIEF PRÉ-REMPLI PAR L'IA", html)
        self.assertIn("Validation du Débrief par le Consultant", html)
        self.assertIn("[ ] Débrief relu et validé par le consultant", html)
        self.assertIn("Valider le débrief en 1 clic", html)
        self.assertIn(validation_url, html)

        # 2. Prefilled content bullets
        self.assertIn("Challenge 1: Fragmentation", html)
        self.assertIn("Vertex AI", html)
        self.assertIn("99.8% disponibilité", html)

        # 3. Visual deliverables table
        self.assertIn("arch_gcp.png", html)
        self.assertIn("Slide 2 : Blueprint Technique", html)

        # 4. Persona preview
        self.assertIn("Déclinaison Multi-Persona Prévue", html)
        self.assertIn("Executive summary preview", html)
        self.assertIn("Technical blueprint preview", html)


class TestPrefilledKickoffEmailHTML(unittest.TestCase):
    """Verifies kickoff email HTML template in standard and prefilled modes."""

    def test_standard_kickoff_email(self):
        html = build_kickoff_email_html(
            mission_name="Mission Standard",
            client="L'Oréal",
            lead_email="lead@artefact.com",
            team_emails=["consultant@artefact.com"],
            deadline_str="2026-11-20",
            doc_url="https://docs.google.com/doc1",
            visuals_url="https://drive.google.com/vis1",
            folder_url="https://drive.google.com/folder1",
            folder_name="[EOM] L'Oréal",
            is_prefilled=False
        )
        self.assertIn("Mission Standard", html)
        self.assertNotIn("Synthèse Pré-Remplie", html)
        self.assertNotIn("Revue Rapide (3 minutes)", html)

    def test_prefilled_kickoff_email(self):
        val_url = "https://eom.artefact.com/debrief/validate?folder_id=f123"
        html = build_kickoff_email_html(
            mission_name="GenAI Observability",
            client="Ferrero",
            lead_email="lead@artefact.com",
            team_emails=["consultant@artefact.com"],
            deadline_str="2026-11-20",
            doc_url="https://docs.google.com/doc1",
            visuals_url="https://drive.google.com/vis1",
            folder_url="https://drive.google.com/folder1",
            folder_name="[EOM] Ferrero",
            is_prefilled=True,
            validation_url=val_url
        )
        self.assertIn("Synthèse Pré-Remplie", html)
        self.assertIn("3 minutes de relecture suffisent", html)
        self.assertIn("Valider en 1 Clic", html)
        self.assertIn(val_url, html)


class TestDebriefValidationDetection(unittest.TestCase):
    """Verifies that check_debrief_doc_completion detects consultant validation."""

    @patch("eom_agent.workspace_service.get_drive_service")
    def test_checkbox_validation_detected(self, mock_drive):
        fake_text = """
⚡ DÉBRIEF PRÉ-REMPLI PAR L'IA
Validation du Débrief par le Consultant

1. Challenge (Contexte & Problématique Client)
Contexte précis sur la mission Ferrero avec métriques de production et analyse d'impact métier approfondie.

2. Solution (Livrables & Architecture Déployée)
Architecture basée sur GKE et OpenTelemetry pour la supervision des clusters et du pipeline.

3. Results & Impact (KPIs & Valeur Métier Générée)
99.8% de disponibilité et 45% de temps gagné sur la résolution des incidents techniques.

4. Visuels & Schémas d'Architecture
- Diagramme GCP

[X] Débrief relu et validé par le consultant
"""
        mock_drive_inst = MagicMock()
        mock_drive_inst.files().get().execute.return_value = {
            "id": "fake_doc_id",
            "name": "[Debrief EOM] Ferrero",
            "mimeType": "application/vnd.google-apps.document"
        }
        mock_drive_inst.files().export().execute.return_value = fake_text.encode("utf-8")
        mock_drive.return_value = mock_drive_inst

        status = check_debrief_doc_completion("fake_doc_id", creds=MagicMock())
        self.assertTrue(status["isCompleted"])
        self.assertTrue(status["isValidated"])
        self.assertTrue(status["isPrefilled"])

    @patch("eom_agent.workspace_service.get_drive_service")
    def test_unvalidated_checkbox_detected(self, mock_drive):
        fake_text = """
1. Challenge (Contexte & Problématique Client)
Contexte précis sur la mission Ferrero avec métriques de production et analyse d'impact métier approfondie.

2. Solution (Livrables & Architecture Déployée)
Architecture basée sur GKE et OpenTelemetry pour la supervision des clusters et du pipeline.

3. Results & Impact (KPIs & Valeur Métier Générée)
99.8% de disponibilité et 45% de temps gagné sur la résolution des incidents techniques.

4. Visuels & Schémas d'Architecture
- Diagramme GCP

[ ] Débrief relu et validé par le consultant
"""
        mock_drive_inst = MagicMock()
        mock_drive_inst.files().get().execute.return_value = {
            "id": "fake_doc_id",
            "name": "[Debrief EOM] Ferrero",
            "mimeType": "application/vnd.google-apps.document"
        }
        mock_drive_inst.files().export().execute.return_value = fake_text.encode("utf-8")
        mock_drive.return_value = mock_drive_inst

        status = check_debrief_doc_completion("fake_doc_id", creds=MagicMock())
        self.assertTrue(status["isCompleted"])
        self.assertFalse(status["isValidated"])
        self.assertTrue(status["isPrefilled"])


class TestPydanticDebriefModels(unittest.TestCase):
    """Verifies request validation for new Pydantic models."""

    def test_validate_debrief_request_parsing(self):
        req = ValidateDebriefRequest(
            folderId="fold_123",
            docId="doc_456",
            client="Ferrero",
            leadEmail="lead@artefact.com",
            missionName="Mission Ferrero",
            ccEmails=["lead2@artefact.com"]
        )
        self.assertEqual(req.get_folder_id(), "fold_123")
        self.assertEqual(req.get_doc_id(), "doc_456")
        self.assertEqual(req.get_lead_email(), "lead@artefact.com")
        self.assertEqual(req.get_mission_name(), "Mission Ferrero")

        # snake_case alias
        req2 = ValidateDebriefRequest(
            folder_id="fold_789",
            lead_email="lead2@artefact.com"
        )
        self.assertEqual(req2.get_folder_id(), "fold_789")
        self.assertEqual(req2.get_lead_email(), "lead2@artefact.com")

        # Missing folderId error
        with self.assertRaises(ValueError):
            ValidateDebriefRequest().get_folder_id()

    def test_prefill_debrief_request_parsing(self):
        req = PrefillDebriefRequest(
            folderId="1FdU3qyctloguhTWGj99ZtbayB1gg0p4R",
            client="Ferrero",
            leadEmail="ayrton.andre@artefact.com",
            missionName="Ferrero Observability",
            prefilledPayload={"challenge": ["test"]}
        )
        self.assertEqual(req.get_folder_id(), "1FdU3qyctloguhTWGj99ZtbayB1gg0p4R")
        self.assertEqual(req.client, "Ferrero")
        self.assertEqual(req.get_prefilled_payload(), {"challenge": ["test"]})

    def test_wrapup_mission_request_parsing(self):
        req = WrapupMissionRequest(
            folder_id="fold_abc",
            mission_name="Mission ABC",
            client="Client ABC",
            lead_email="lead@artefact.com",
            persona_cards={"executive": {"synthesis": "done"}}
        )
        self.assertEqual(req.get_folder_id(), "fold_abc")
        self.assertEqual(req.get_mission_name(), "Mission ABC")
        self.assertEqual(req.get_persona_cards()["executive"]["synthesis"], "done")


class TestFastAPIDebriefEndpoints(unittest.TestCase):
    """Verifies FastAPI routes for debrief prefill, validation and wrapup."""

    @patch("service.main.handle_wrapup_mission")
    def test_get_debrief_validate_html(self, mock_wrapup):
        mock_wrapup.return_value = {
            "status": "MISSION_WRAPPED_UP",
            "missionName": "Ferrero Observability",
            "client": "Ferrero",
            "leadEmail": "ayrton.andre@artefact.com",
            "folderId": "f123",
            "folderUrl": "https://drive.google.com/folders/f123",
            "docId": "d123",
            "docUrl": "https://docs.google.com/document/d/d123/edit",
            "slideId": "s123",
            "slideUrl": "https://docs.google.com/presentation/d/s123/edit",
            "slidesCount": 4,
            "imagesAttached": 2,
            "sheetId": "sh123",
            "sheetUrl": "https://docs.google.com/spreadsheets/d/sh123/edit",
            "auditRowsCount": 8,
            "emailStatus": "SENT"
        }

        resp = client.get("/debrief/validate?folder_id=f123&client=Ferrero")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])
        self.assertIn("Débrief Approuvé", resp.text)
        self.assertIn("Deck Google Slides (4 slides (2 visuels intégrés))", resp.text)
        self.assertIn("https://docs.google.com/presentation/d/s123/edit", resp.text)
        self.assertIn("https://docs.google.com/spreadsheets/d/sh123/edit", resp.text)

    @patch("service.main.handle_wrapup_mission")
    def test_get_debrief_validate_json_accept(self, mock_wrapup):
        mock_wrapup.return_value = {
            "status": "MISSION_WRAPPED_UP",
            "missionName": "Ferrero Observability",
            "client": "Ferrero"
        }
        resp = client.get("/debrief/validate?folder_id=f123", headers={"Accept": "application/json"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "MISSION_WRAPPED_UP")

    @patch("service.main.handle_wrapup_mission")
    def test_post_debrief_validate(self, mock_wrapup):
        mock_wrapup.return_value = {
            "status": "MISSION_WRAPPED_UP",
            "missionName": "Ferrero Observability"
        }
        resp = client.post("/debrief/validate", json={"folderId": "f123", "client": "Ferrero"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "MISSION_WRAPPED_UP")

    @patch("service.main.handle_prefill_debrief_doc")
    def test_post_debrief_prefill(self, mock_prefill):
        mock_prefill.return_value = {
            "status": "DEBRIEF_PREFILLED_AWAITING_CHECK",
            "missionName": "Ferrero Observability",
            "client": "Ferrero",
            "docUrl": "https://docs.google.com/d123",
            "validationUrl": "https://service/debrief/validate?folder_id=f123"
        }
        resp = client.post("/debrief/prefill", json={"folderId": "f123", "client": "Ferrero"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "DEBRIEF_PREFILLED_AWAITING_CHECK")

    @patch("service.main.handle_wrapup_mission")
    def test_post_mission_wrapup(self, mock_wrapup):
        mock_wrapup.return_value = {
            "status": "MISSION_WRAPPED_UP",
            "slideUrl": "https://slides/123",
            "sheetUrl": "https://sheets/123"
        }
        resp = client.post("/mission/wrapup", json={"folderId": "f123", "client": "Ferrero"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "MISSION_WRAPPED_UP")


class TestHumanizerRulesCompliance(unittest.TestCase):
    """Verifies compliance with GEMINI.md humanizer rules for user-facing French text."""

    def test_render_debrief_validation_success_page_cleanliness(self):
        html = render_debrief_validation_success_page(
            client="Ferrero",
            mission_name="Ferrero Observability",
            slide_url="https://slides/s1",
            sheet_url="https://sheets/sh1",
            folder_url="https://drive/f1",
            doc_url="https://docs/d1",
            slides_count=4,
            images_attached=3
        )

        # Prohibited AI tells & buzzwords from GEMINI.md
        banned_words = [
            "crucial", "pivotal", "au cœur de", "paysage", "robuste", "sans couture",
            "témoigner de", "mettre en lumière", "façonner", "catalyseur", "levier stratégique",
            "plonger dans", "méticuleux", "tapisserie", "écosystème", "dynamique", "incontournable"
        ]
        for w in banned_words:
            self.assertNotIn(w, html.lower(), f"Banned word '{w}' found in success page HTML")

        # No em dash (—) or en dash (–)
        self.assertNotIn("—", html)
        self.assertNotIn("–", html)

        # No shallow trailing -ant clauses (e.g. "garantissant ainsi...", "permettant de...")
        self.assertFalse(re.search(r"\b\w+ant ainsi\b", html, re.IGNORECASE))
        self.assertFalse(re.search(r"\bpermettant ainsi\b", html, re.IGNORECASE))

        # Direct, concrete phrasing present
        self.assertIn("Débrief Approuvé", html)
        self.assertIn("Ferrero Observability", html)
        self.assertIn("4 slides (3 visuels intégrés)", html)


class TestAgentToolsRegistration(unittest.TestCase):
    """Verifies that prefill and wrapup tools are exposed in tools.py and registered in root_agent."""

    def test_tools_callable(self):
        self.assertTrue(callable(prefill_mission_debrief))
        self.assertTrue(callable(wrapup_mission_deliverables))

    def test_root_agent_registration(self):
        tool_names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in root_agent.tools]
        self.assertIn("prefill_mission_debrief", tool_names)
        self.assertIn("wrapup_mission_deliverables", tool_names)

    def test_root_agent_instructions_scenario(self):
        self.assertIn("Scenario A-Prefill", root_agent.instruction)
        self.assertIn("prefill_mission_debrief", root_agent.instruction)
        self.assertIn("wrapup_mission_deliverables", root_agent.instruction)


if __name__ == "__main__":
    unittest.main()
