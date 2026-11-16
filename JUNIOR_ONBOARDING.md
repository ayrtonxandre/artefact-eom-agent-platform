# Junior Developer & Consultant Onboarding Guide
## Artefact End-of-Mission (EOM) Autonomous Pipeline

Welcome to the **Artefact EOM Agent Platform**. This guide walks you through setting up your local environment, authenticating with Google Workspace and Google Cloud Platform, running the test suite, and launching the service.

---

## 1. Prerequisites

Make sure you have the following installed on your machine:
- **Python**: Version `3.10` or `3.11` (Python 3.11 is recommended).
- **Git**: Configured with your GitHub SSH key or personal access token.
- **Web Browser**: Google Chrome or Firefox (for Google OAuth authorization).
- **Google Workspace Account**: An active `@artefact.com` account with access to the project drives.

---

## 2. Step 1: Clone the Repository

Clone the repository to your local workspace:

```bash
git clone git@github.com:ayrtonxandre/artefact-eom-agent-platform.git
cd artefact-eom-agent-platform
```

---

## 3. Step 2: Create a Virtual Environment & Install Dependencies

Create and activate a dedicated Python virtual environment:

```bash
# Create virtual environment
python3 -m venv .venv

# Activate it (macOS / Linux)
source .venv/bin/activate

# On Windows (PowerShell)
# .venv\Scripts\Activate.ps1

# Upgrade pip
pip install --upgrade pip

# Install all dependencies (service, agent, and test suite)
pip install -r requirements.txt
```

---

## 4. Step 3: Configure Environment Variables

Copy the example environment configuration:

```bash
cp .env.example .env
```

The default `.env` is pre-configured with the project settings:
```ini
# Google Cloud Platform & Vertex AI
GOOGLE_CLOUD_PROJECT=privategpt-437907
GOOGLE_CLOUD_LOCATION=europe-west1
GOOGLE_GENAI_USE_ENTERPRISE=true

# Service Account & OAuth Tokens
GOOGLE_APPLICATION_CREDENTIALS=service_account.json
DRIVE_TOKEN_PATH=drive_token.json

# BigQuery Mission Tracking
BQ_PROJECT_ID=privategpt-437907
BQ_DATASET_ID=eom_pipeline
BQ_MISSIONS_TABLE=missions
MOCK_BQ=true

# Central Tracker & Server Port
CENTRAL_TRACKER_ID=1hIekn1kE1_3Yg80Kx73z_c42f_E4M5A
PORT=8080
```

> If you are working offline or do not have BigQuery write access, keep `MOCK_BQ=true`.

---

## 5. Step 4: Add Secret Credentials (Out of Band)

For security reasons, private keys and client secrets are **never** committed to Git (`.gitignore` protects them). Obtain the following two files from your project lead (via 1Password or encrypted transfer) and place them at the root of the project:

1. **`service_account.json`**:
   - Used for Vertex AI (`gemini-2.5-flash`) and BigQuery operations.
   - Project: `privategpt-437907`.
2. **`credentials.json`**:
   - Google OAuth 2.0 Desktop Client secret used to authorize your personal `@artefact.com` Google account for Drive, Docs, Slides, Sheets, and Gmail operations.

Verify they are in your root folder:
```bash
ls -la service_account.json credentials.json
```

---

## 6. Step 5: Authorize Google Workspace (Generate `drive_token.json`)

To read Google Drive mission files and generate Docs, Slides, and Sheets under your Artefact identity, run the OAuth authorization flow:

```bash
python auth_flow.py
```

1. A local web server starts on port `8085`.
2. Your default browser opens automatically to the Google Accounts login page.
3. Select your `@artefact.com` account.
4. Click **Advanced** > **Proceed to Artefact EOM (unsafe)** if prompted with an unverified app warning.
5. Grant permissions for Google Drive, Slides, Spreadsheets, and Gmail.
6. The terminal outputs `Authentication successful!` and creates `drive_token.json` at the project root.

> `drive_token.json` automatically refreshes its token on expiration. You do not need to rerun `auth_flow.py` unless permissions change.

---

## 7. Step 6: Verify Environment with the Test Suite

Run the complete test suite. All 41 tests run offline using mocks and do not require active network calls:

```bash
pytest tests/ -v
```

Expected result:
```
======================== 41 passed in 2.0s ========================
```

The test suite covers:
- Pydantic models and request validation (`test_service_contracts.py`).
- HTML email and debrief document rendering.
- Multi-persona slide generation and anonymization algorithms.
- AI prefill and debrief checkbox validation endpoints (`test_prefilled_debrief_contracts.py`).
- Root agent tool registrations and OpenAPI schema structure.

---

## 8. Step 7: Launch the Local API Server

Launch the FastAPI application with hot reload:

```bash
uvicorn service.main:app --reload --port 8080
```

Once running, access:
- **Interactive Swagger Documentation**: [http://localhost:8080/docs](http://localhost:8080/docs)
- **ReDoc Documentation**: [http://localhost:8080/redoc](http://localhost:8080/redoc)
- **Health Check**: [http://localhost:8080/healthz](http://localhost:8080/healthz)

---

## 9. Key API Workflows

### 1. Prefill Debrief Document (`POST /debrief/prefill`)
Reads deliverables from the mission's Drive folder (including PDFs, specs, slide decks), runs Vertex AI synthesis, and populates the Google Doc with a prefilled debrief:
```bash
curl -X POST http://localhost:8080/debrief/prefill \
  -H "Content-Type: application/json" \
  -d '{
    "missionId": "MISSION_FERRERO_2025",
    "missionName": "Ferrero - Data Governance Assessment",
    "folderId": "YOUR_DRIVE_FOLDER_ID",
    "debriefDocId": "YOUR_DEBRIEF_DOC_ID",
    "consultantEmail": "consultant@artefact.com"
  }'
```

### 2. Validate Debrief & Auto-Trigger Wrap-up (`POST /debrief/validate`)
Verifies if the consultant checked `[x]` on the Google Doc. If validated, it automatically invokes the wrap-up generator:
```bash
curl -X POST http://localhost:8080/debrief/validate \
  -H "Content-Type: application/json" \
  -d '{
    "missionId": "MISSION_FERRERO_2025",
    "missionName": "Ferrero - Data Governance Assessment",
    "debriefDocId": "YOUR_DEBRIEF_DOC_ID",
    "folderId": "YOUR_DRIVE_FOLDER_ID",
    "leadEmail": "lead@artefact.com"
  }'
```

### 3. Generate Multi-Persona Slide Deck (`POST /mission/wrapup`)
Generates the 2025 Artefact master slide deck tailored to 4 consultant personae:
- **Slide 1**: Executive / C-Level
- **Slide 2**: Tech & Architecture
- **Slide 3**: Pure Knowledge & Methods
- **Slide 4**: Referential & Case Study (fully anonymized)

---

## 10. Repository File Map

```
artefact-eom-agent-platform/
├── eom_agent/
│   ├── agent.py               # ADK Root Orchestrator and specialized subagents
│   ├── tools.py               # Agent tool wrappers (ADK integration)
│   ├── workspace_service.py   # Google Drive, Slides, Sheets, Docs, and Gmail engine
│   └── bigquery_service.py    # BigQuery tracker service with mock fallback
├── service/
│   ├── main.py                # FastAPI REST endpoints and lifespan handlers
│   ├── Dockerfile             # Production Cloud Run container build
│   └── deploy.sh              # Google Cloud Run deployment script
├── tests/
│   ├── test_service_contracts.py           # Core Pydantic, HTML, and Slides tests
│   └── test_prefilled_debrief_contracts.py # Prefill, Validation, and Tool tests
├── auth_flow.py               # Google OAuth 2.0 desktop token generator
├── requirements.txt           # Unified project dependencies
├── openapi.json / .yaml       # Machine-readable API definitions
├── .env.example               # Template environment configuration
└── JUNIOR_ONBOARDING.md       # This onboarding guide
```

---

## 11. Troubleshooting

- **`Address already in use: ('localhost', 8085)` during `auth_flow.py`**:
  Another process is using port 8085. Find and kill it:
  ```bash
  lsof -ti :8085 | xargs kill -9
  ```
- **`Token has been expired or revoked`**:
  Delete `drive_token.json` and rerun `python auth_flow.py`.
- **`ModuleNotFoundError`**:
  Confirm that your virtual environment is activated (`source .venv/bin/activate`) and run `pip install -r requirements.txt`.
