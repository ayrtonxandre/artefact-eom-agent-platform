# Google Cloud Agent Platform Migration Guide: Artefact EOM Pipeline

This guide provides the exact configuration and prompts to configure your agent in **Google Cloud Agent Platform (Agent Designer)** for agent ID:
`agent_1791546784802` in project `privategpt-437907`.

---

## 1. Architecture Overview

```
                      +---------------------------------------+
                      |       USER / TRIGGER PROMPT           |
                      |  Folder URL + Mission Lead Email      |
                      +-------------------+-------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |   EOM Mission Orchestrator (Main)     |
                      |          (Gemini 2.5 Flash)           |
                      +-------+-----------------------+-------+
                              |                       |
            +-----------------+                       +-----------------+
            v                                                           v
+-------------------------------+                           +-------------------------------+
| Subagent 1:                   |                           | Subagent 2:                   |
| Executive-Synthesizer         |                           | Security-Auditor              |
| (Principal Partner Persona)   |                           | (Compliance Auditor Persona)  |
+---------------+---------------+                           +---------------+---------------+
                |                                                           |
                +-----------------------------+-----------------------------+
                                              |
                                              v
                              +-------------------------------+
                              |    OpenAPI Workspace Tools    |
                              |  (Cloud Run / Cloud Function) |
                              +---------------+---------------+
                                              |
                 +----------------------------+----------------------------+
                 |                            |                            |
                 v                            v                            v
       +-------------------+        +-------------------+        +-------------------+
       |   Google Drive    |        |   Google Slides   |        |   Google Sheets   |
       |  Extract Docs     |        |  Clone & Populate |        |  Risk Matrix &    |
       |                   |        |  4-Card One-Pager |        |  Checklist Table  |
       +-------------------+        +-------------------+        +-------------------+
```

---

## 2. Main Agent Configuration

In **Google Cloud Console** -> **Agent Designer**:
* **URL**: `https://console.cloud.google.com/agent-platform/studio/agent-designer/edit/agent_1791546784802?project=privategpt-437907`
* **Agent Name**: `Artefact EOM Mission Orchestrator`
* **Model**: `gemini-2.5-flash` (or `gemini-1.5-pro`)
* **Description**:
  ```text
  Autonomous End-of-Mission debriefing pipeline for Artefact. Extracts project documentation from Google Drive, orchestrates executive synthesis into client-ready Google Slides, audits confidentiality risks in Google Sheets, and dispatches lead notifications.
  ```

### System Instructions (Copy & Paste)
```text
You are the Lead Project Operations Orchestrator at Artefact.
Your mission is to autonomously manage the end-of-mission debriefing and knowledge curation pipeline.

Tool & MCP Server Access:
- All workspace operations are provided by the MCP server `eom-workspace-service`.
- When accessing tools, invoke them directly through the `eom-workspace-service` toolset:
  * `extract_folder_documents`: Extracts text content and file metadata from the mission's Google Drive folder.
  * `generate_one_pager_slide`: Generates the executive summary Google Slides deck from the template.
  * `create_audit_sheet`: Creates the Google Sheets confidentiality audit checklist.
  * `send_lead_notification`: Dispatches completion notification emails via Gmail.
- Do NOT use GoogleSearchAgent or external web search.
- Use `transfer_to_agent` strictly for delegating synthesis and auditing tasks to subagents.

CRITICAL EXECUTION ORDER:
When provided with a Google Drive folder URL or ID and a Lead Email:
Step 1 [LOCAL ACTION - DO NOT DELEGATE]:
Extract the folder ID from the provided URL/string and IMMEDIATELY call `extract_folder_documents` from `eom-workspace-service` yourself.
DO NOT call `transfer_to_agent` before you have completed this step! You must have the extracted document texts in hand before contacting any subagent.

Step 2:
Infer the mission name from the folder metadata returned by `extract_folder_documents`. If the folder is empty or no files are returned, inform the user immediately.

Step 3 [DELEGATE TO EXECUTIVE-SYNTHESIZER]:
Call `transfer_to_agent` targeting `Executive-Synthesizer`. Provide the extracted document contents and request the 4-card executive debrief JSON:
- context
- deliverables
- businessImpact
- recommendations
- synthesis
Wait for the subagent to complete and return the JSON.

Step 4 [DELEGATE TO SECURITY-AUDITOR]:
Call `transfer_to_agent` targeting `Security-Auditor`. Provide the file list and request the confidentiality risk classification JSON array (CRITICAL, HIGH, MEDIUM, LOW) and "toBeExported" recommendations.
Wait for the subagent to complete and return the JSON array.

Step 5 [GENERATE DELIVERABLES]:
Call `generate_one_pager_slide` from `eom-workspace-service` passing the folder ID, mission name, and the 4-card debrief from Executive-Synthesizer.

Step 6 [CREATE AUDIT SHEET]:
Call `create_audit_sheet` from `eom-workspace-service` passing the folder ID, mission name, and the audit records array from Security-Auditor.

Step 7 [SEND NOTIFICATION]:
Call `send_lead_notification` from `eom-workspace-service` with the recipient email, mission name, slide URL, and sheet URL.

Step 8 [FINAL RESPONSE]:
Present a clean markdown summary table to the user with direct links to:
- Generated Google Slides One-Pager
- Generated Google Sheets Knowledge Audit
- Confirmation of email delivery to the Lead
```

---

## 3. Subagents Configuration

In the Agent Designer left navigation panel, click **+ Add Subagent** or define routing flows:

### Subagent 1: `Executive-Synthesizer`
* **Display Name**: `Executive-Synthesizer`
* **Model**: `gemini-2.5-flash`
* **Description**: Synthesizes mission documentation into Artefact C-level executive summary cards.
* **Instructions**:
```text
You are a Principal Consulting Partner at Artefact.
Analyze the provided mission documentation and generate a structured C-level executive debrief divided into 4 specific cards.

Tool & MCP Server Access:
- If additional mission documents or details are needed, access them via the `extract_folder_documents` tool from the `eom-workspace-service` MCP server.
- Once synthesis is completed, return the structured JSON result to the orchestrator.

Return STRICTLY a JSON object matching this schema:
{
  "context": "2-3 concise sentences on client background, initial problem, and mission objectives.",
  "deliverables": "Bullet points summarizing the core technical solutions, models, architecture, and deliverables built.",
  "businessImpact": "Quantifiable business impact, performance gains, ROI, efficiency improvements, or strategic value.",
  "recommendations": "Critical takeaways, operational recommendations, and next steps for the client or team.",
  "synthesis": "An integrated executive summary combining the above."
}

Style Guidelines:
- Professional, analytical, authoritative consulting tone.
- Highlighting quantifiable metrics where present (e.g. % accuracy, hours saved, cost reductions, revenue uplift).
- Emphasize Artefact's strategic delivery and technical excellence.
```

---

### Subagent 2: `Security-Auditor`
* **Display Name**: `Security-Auditor`
* **Model**: `gemini-2.5-flash`
* **Description**: Audits project deliverables for confidentiality risks and categorizes assets for internal Know sharing.
* **Instructions**:
```text
You are an Information Security and Knowledge Management auditor at Artefact.
Evaluate the provided project files from the mission.

Tool & MCP Server Access:
- If additional file content or metadata inspection is required, access them via the `extract_folder_documents` tool from the `eom-workspace-service` MCP server.
- Once the audit is completed, return the structured JSON array to the orchestrator.

For each file:
1. Assess "confidentialityRisk": One of ["LOW", "MEDIUM", "HIGH", "CRITICAL"].
   - CRITICAL: Contains raw PII, sensitive patient/health data (e.g. CNIL/GDPR sensitive), production credentials, or strict NDA client IP.
   - HIGH: Contains internal financial data, detailed contracts, or proprietary client business logic.
   - MEDIUM: Contains sanitized deliverables, architecture blueprints, or generic workflows.
   - LOW: Publicly shareable frameworks, standard methodology, or sanitized templates.
2. Suggest 2-4 categorization "suggestedTags" (comma-separated string).
3. Determine "toBeExported": Boolean (true if suitable for internal knowledge base without leaking client secrets; false if highly sensitive or irrelevant).

Return STRICTLY a JSON array matching this schema:
[
  {
    "filename": "string",
    "confidentialityRisk": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
    "suggestedTags": "string",
    "toBeExported": boolean
  }
]
```

---

## 4. OpenAPI Tools Configuration

### Step 4.1: Register the Tool in the Catalog
In **Agent Designer** -> **Tools** (left navigation) -> **Create Tool**:
1. **Tool Name**: `eom_workspace_tools`
2. **Type**: `OpenAPI`
3. **Spec**: Select **Upload** and upload `eom_agent_platform/openapi.yaml` (or copy/paste from `openapi.json`).
4. **Operations Imported**:
   - `extract_folder_documents` (`POST /extract-documents`)
   - `generate_one_pager_slide` (`POST /generate-slide`)
   - `create_audit_sheet` (`POST /create-audit-sheet`)
   - `send_lead_notification` (`POST /send-notification`)

### Step 4.2: Attach the Tool to the Orchestrator Agent (CRITICAL)
Creating the tool in the catalog does **not** automatically attach it to your agent:
1. Return to the **Artefact EOM Mission Orchestrator** agent edit page.
2. Under the **Tools** section:
   - Click **+ Add Tool** (or manage tools).
   - Select and check **`eom_workspace_tools`** (all 4 operations).
   - **Remove / Uncheck `GoogleSearchAgent`** (if present by default), as the orchestrator should only call the workspace tools and transfer to subagents.
3. Click **Save** / **Deploy**.

---

## 5. Deploying the Tool Microservice to Cloud Run

The backend microservice is prepared in `eom_agent_platform/service/`.

To deploy it in your GCP project `privategpt-437907`:

```bash
cd /Users/ayrtonandre/eom_agent_platform/service

gcloud run deploy eom-workspace-service \
  --project privategpt-437907 \
  --region europe-west1 \
  --source . \
  --platform managed \
  --allow-unauthenticated
```

After deployment, copy the returned Cloud Run URL (e.g. `https://eom-workspace-service-xxxx.a.run.app`) and replace the placeholder in `openapi.yaml` / `openapi.json`:
```yaml
servers:
  - url: https://eom-workspace-service-xxxx.a.run.app
```

---

## 6. Testing & Validation

Once configured, trigger the agent using the test chat in the Agent Designer console:

### Test Input:
```text
Run the End of Mission automation for folder https://drive.google.com/drive/folders/1oqx6AT98K36xUOM2G_UYKBRGMfv_ub-U and notify ayrton.andre@artefact.com
```

### Expected Agent Behavior:
1. Calls `extract_folder_documents` with folder ID `1oqx6AT98K36xUOM2G_UYKBRGMfv_ub-U`.
2. Passes document text to `Executive-Synthesizer` to extract the 4 cards.
3. Passes files to `Security-Auditor` to score risk and tags.
4. Calls `generate_one_pager_slide` creating `[One-Pager] EOM` on Google Slides.
5. Calls `create_audit_sheet` creating `[Checklist & Audit] EOM` on Google Sheets with interactive checkboxes.
6. Calls `send_lead_notification` dispatching email to `ayrton.andre@artefact.com`.
7. Outputs confirmation table with links to both generated Google Workspace files.

---

## 7. Troubleshooting Common Errors

### "I am unable to directly call the extract_folder_documents tool. It seems that I can only use GoogleSearchAgent and transfer_to_agent."
* **Cause**: The OpenAPI tool `eom_workspace_tools` was created in the Catalog, but was not attached to the `Artefact EOM Mission Orchestrator` agent. The agent defaults to `GoogleSearchAgent` and the system-generated `transfer_to_agent`.
* **Fix**:
  1. Open the **Artefact EOM Mission Orchestrator** agent in Agent Designer.
  2. Under the **Tools** section, click **+ Add Tool** and attach **`eom_workspace_tools`**.
  3. Remove or uncheck **`GoogleSearchAgent`**.
  4. Save / Deploy the agent and start a **New Session** in the test preview.

### "HttpError 404: File not found: [folderId]"
* **Cause**: Google Drive API returns 404 if the folder does not exist or if the authenticated Google account (`ayrton.andre@artefact.com` / service account) does not have read access to the folder.
* **Fix**: Ensure the folder is shared with `ayrton.andre@artefact.com` (or set link sharing to "Anyone with the link can view"). For quick testing, use the verified test folder: `1oqx6AT98K36xUOM2G_UYKBRGMfv_ub-U`.

### "Invoking 'extract_folder_documents()' failed as no tool with that name is available. The tools you can call are: transfer_to_agent."
* **Cause 1 - Uncommitted Draft**: In Google Cloud Agent Designer, changes made to the flow canvas (such as adding MCP tools) remain in **`Draft`** status until the blue **`Update`** button (top right header) is clicked. The test session was running against an older deployment where tools were not yet registered.
* **Cause 2 - Stale Preview Session**: Running test sessions do not automatically reload when tools are added. Even after clicking `Update`, the user must click **`+ New session`** in the top right of the Preview panel.
* **Cause 3 - Tool Selection Checkboxes**: Inside the Agent edit drawer under **Tools**, clicking the pencil icon (`✏️`) next to `Eom-Workspace-Service` lets you select which operations are enabled. If no operations are checked, 0 tools are exposed. Ensure all 4 operations are checked.
* **Cause 4 - Remove Conflicting `Drivemcp.googleapis.com`**: If an unconfigured or placeholder `Drivemcp.googleapis.com` tool is attached, remove it so only `Eom-Workspace-Service` is attached.
* **Fix Checklist**:
  1. Click the pencil (`✏️`) next to `Eom-Workspace-Service` on `GE - Artefact EOM Mission Orchestrator` to ensure all 4 functions are checked.
  2. Click the trash icon next to `Drivemcp.googleapis.com` to remove it.
  3. Click the blue **`Update`** button in the top right header.
  4. In the **Preview** panel, click **`+ New session`**.
  5. Send the test prompt again.
