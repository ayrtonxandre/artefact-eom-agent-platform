# Artefact End-of-Mission (EOM) Autonomous Pipeline

An enterprise multi-agent pipeline built with **Google Agent Development Kit (ADK)** and **Google Cloud Vertex AI** (`gemini-2.5-flash`), automating mission debriefing, C-level executive presentation generation, confidentiality risk auditing, and team notifications across Google Workspace.

---

## 🏛 Architecture & Multi-Agent Structure

```
                                  ┌──────────────────────────────────────────────┐
                                  │    Artefact_EOM_Mission_Orchestrator         │
                                  │        (Lead Project Operations)             │
                                  └───────────────┬──────────────────────────────┘
                                                  │
                 ┌────────────────────────────────┼────────────────────────────────┐
                 ▼                                ▼                                ▼
  ┌─────────────────────────────┐  ┌─────────────────────────────┐  ┌─────────────────────────────┐
  │    Executive_Synthesizer    │  │      Security_Auditor       │  │       Workspace Tools       │
  │ (Principal Consulting Partner)│  │ (InfoSec / Know Compliance) │  │  Drive / Slides / Sheets /  │
  │   Produces 4-card debrief   │  │ Assesses data confidentiality│  │           Gmail             │
  └─────────────────────────────┘  └─────────────────────────────┘  └─────────────────────────────┘
```

### 1. Agents
* **`Artefact_EOM_Mission_Orchestrator` (Root Agent)**:
  Directs end-of-mission debriefing. Retrieves files from Google Drive, delegates synthesis and audit tasks to specialized subagents, generates artifacts, and dispatches lead notifications.
* **`Executive_Synthesizer` (Subagent)**:
  Emulates an Artefact Principal Consulting Partner. Analyzes technical deliverables and distills findings into a structured 4-card debrief:
  - `Context & Client Objectives`
  - `Key Deliverables & Architecture`
  - `Business Impact & Metrics`
  - `Recommendations & Next Steps`
* **`Security_Auditor` (Subagent)**:
  Emulates an Information Security and Knowledge Management auditor. Audits all mission deliverables for confidentiality risk (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`), suggests tags, and determines internal "Know" export eligibility.

### 2. Workspace Tools
* **`extract_folder_documents`**: Reads text documents, Google Docs, presentations, and code files from a Google Drive folder.
* **`generate_one_pager_slide`**: Clones the Artefact Master Template (`197zP6K146fFlNSPDrDuHoUiKS9c0KODiypl_u27XWDQ`) into the mission folder and replaces placeholders (`{{CONTEXT}}`, `{{DELIVERABLES}}`, `{{BUSINESS_IMPACT}}`, `{{RECOMMENDATIONS}}`, `{{SYNTHESIS}}`).
* **`create_audit_sheet`**: Generates an interactive Google Sheet with formatted headers, auto-resized columns, and validation checkboxes for team review.
* **`send_lead_notification`**: Dispatches an email to the mission lead via Gmail API with links to the generated deck and sheet.

---

## 🚀 Quickstart & Execution

### Prerequisites
- Python 3.10+
- Installed packages: `google-adk`, `google-genai`, `google-api-python-client`, `google-auth-oauthlib`, `fastapi`, `uvicorn`.

### Running Locally with ADK Runner
Run the complete multi-agent pipeline from end to end:
```bash
python3 eom_agent/run_local.py [FOLDER_URL_OR_ID] [LEAD_EMAIL]
```

Default parameters:
* Folder: `https://drive.google.com/drive/folders/1oqx6AT98K36xUOM2G_UYKBRGMfv_ub-U` (Mission Clariane)
* Lead Email: `ayrton.andre@artefact.com`

### Running with ADK Visual Web UI
Launch the ADK web canvas to visually trace agent handoffs and tool executions:
```bash
adk web eom_agent
```
Open `http://127.0.0.1:8000` in your browser.

---

## 🔒 Authentication & Credentials

1. **Vertex AI (LLM Reasoning)**:
   - Authenticated via Service Account: `eom-chat-ap@privategpt-437907.iam.gserviceaccount.com`.
   - Credentials file: `service_account.json`.
   - Configured for `europe-west1` with `gemini-2.5-flash`.

2. **Google Workspace (Drive, Slides, Sheets, Gmail)**:
   - Authenticated via User OAuth with full scopes.
   - Credentials file: `drive_token.json` (also linked to `~/.config/gcloud/application_default_credentials.json`).
   - If token refresh is required, run `python3 auth_flow.py`.

---

## ☁️ Cloud Deployment (Agent Platform Integration)

If connecting the agent to the Google Cloud Agent Platform Designer web canvas:
1. Deploy the tool execution microservice to Cloud Run:
   ```bash
   cd service
   ./deploy.sh
   ```
2. Import `openapi.yaml` into your Google Cloud Agent Designer tool configuration.
