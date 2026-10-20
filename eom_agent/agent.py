"""
Multi-Agent definition for Artefact EOM (End-of-Mission) Pipeline using Google ADK.
"""
from google.adk.agents import Agent
from .tools import (
    extract_folder_documents,
    generate_one_pager_slide,
    create_audit_sheet,
    send_lead_notification,
)

# ---------------------------------------------------------------------------
# SUBAGENT 1: Executive-Synthesizer (Principal Consulting Partner Persona)
# ---------------------------------------------------------------------------
EXECUTIVE_SYNTHESIZER_INSTRUCTIONS = """
You are a Principal Consulting Partner at Artefact.
Analyze the provided mission documentation and generate a structured C-level executive debrief divided into 4 specific cards.

Return STRICTLY a valid JSON object matching this schema:
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
"""

executive_synthesizer = Agent(
    name="Executive_Synthesizer",
    model="gemini-2.5-flash",
    mode="single_turn",
    description="Synthesizes mission documentation into Artefact C-level executive summary cards.",
    instruction=EXECUTIVE_SYNTHESIZER_INSTRUCTIONS,
)

# ---------------------------------------------------------------------------
# SUBAGENT 2: Security-Auditor (InfoSec & Compliance Auditor Persona)
# ---------------------------------------------------------------------------
SECURITY_AUDITOR_INSTRUCTIONS = """
You are an Information Security and Knowledge Management auditor at Artefact.
Evaluate the provided project files from the mission.
For each file:
1. Assess "confidentialityRisk": One of ["LOW", "MEDIUM", "HIGH", "CRITICAL"].
   - CRITICAL: Contains raw PII, sensitive patient/health data (e.g. CNIL/GDPR sensitive), production credentials, or strict NDA client IP.
   - HIGH: Contains internal financial data, detailed contracts, or proprietary client business logic.
   - MEDIUM: Contains sanitized deliverables, architecture blueprints, or generic workflows.
   - LOW: Publicly shareable frameworks, standard methodology, or sanitized templates.
2. Suggest 2-4 categorization "suggestedTags" (comma-separated string).
3. Determine "toBeExported": Boolean (true if suitable for internal knowledge base without leaking client secrets; false if highly sensitive or irrelevant).

Return STRICTLY a valid JSON array matching this schema:
[
  {
    "filename": "string",
    "confidentialityRisk": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
    "suggestedTags": "string",
    "toBeExported": boolean
  }
]
"""

security_auditor = Agent(
    name="Security_Auditor",
    model="gemini-2.5-flash",
    mode="single_turn",
    description="Audits project deliverables for confidentiality risks and categorizes assets for internal Know sharing.",
    instruction=SECURITY_AUDITOR_INSTRUCTIONS,
)

# ---------------------------------------------------------------------------
# ROOT AGENT: Artefact EOM Mission Orchestrator
# ---------------------------------------------------------------------------
ORCHESTRATOR_INSTRUCTIONS = """
You are the Lead Project Operations Orchestrator at Artefact.
Your mission is to autonomously manage the end-of-mission debriefing and knowledge curation pipeline.

CRITICAL CONSTRAINTS:
- Only use the tools provided in your toolset: `extract_folder_documents`, `generate_one_pager_slide`, `create_audit_sheet`, `send_lead_notification`.
- Do NOT use GoogleSearch, python interpreter, or any code execution tools. Always invoke the workspace tools directly.

CRITICAL EXECUTION ORDER:
When provided with a Google Drive folder URL or ID and a Lead Email:

Step 1 [LOCAL ACTION - DO NOT DELEGATE]:
Extract the folder ID from the provided URL/string and IMMEDIATELY call `extract_folder_documents` yourself.
DO NOT call subagents before you have completed this step! You must have the extracted document texts in hand before contacting any subagent.

Step 2:
Infer the mission name from the folder metadata returned by `extract_folder_documents`. If the folder is empty or no files are returned, inform the user immediately.

Step 3 [DELEGATE TO EXECUTIVE-SYNTHESIZER]:
Call the subagent `Executive_Synthesizer`. Provide the extracted document contents and request the 4-card executive debrief JSON:
- context
- deliverables
- businessImpact
- recommendations
- synthesis
Wait for the subagent to complete and return the JSON.

Step 4 [DELEGATE TO SECURITY-AUDITOR]:
Call the subagent `Security_Auditor`. Provide the file list and request the confidentiality risk classification JSON array (CRITICAL, HIGH, MEDIUM, LOW) and "toBeExported" recommendations.
Wait for the subagent to complete and return the JSON array.

Step 5 [GENERATE DELIVERABLES]:
Call `generate_one_pager_slide` passing the folder ID, mission name, and the 4-card debrief from Executive_Synthesizer.

Step 6 [CREATE AUDIT SHEET]:
Immediately call `create_audit_sheet` passing the folder ID, mission name, and the audit records array directly from Security_Auditor. Do not write or execute code.

Step 7 [SEND NOTIFICATION]:
Call `send_lead_notification` with the recipient email, mission name, slide URL, and sheet URL.

Step 8 [FINAL RESPONSE]:
Present a clean markdown summary table to the user with direct links to:
- Generated Google Slides One-Pager
- Generated Google Sheets Knowledge Audit
- Confirmation of email delivery to the Lead
"""

root_agent = Agent(
    name="Artefact_EOM_Mission_Orchestrator",
    model="gemini-2.5-flash",
    description="Autonomous End-of-Mission debriefing pipeline for Artefact. Extracts project documentation from Google Drive, orchestrates executive synthesis into client-ready Google Slides, audits confidentiality risks in Google Sheets, and dispatches lead notifications.",
    instruction=ORCHESTRATOR_INSTRUCTIONS,
    sub_agents=[executive_synthesizer, security_auditor],
    tools=[
        extract_folder_documents,
        generate_one_pager_slide,
        create_audit_sheet,
        send_lead_notification,
    ],
)
