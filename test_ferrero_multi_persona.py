"""
Live verification script for Ferrero mission multi-persona 4-slide deck generation.
"""
import os
import sys
import certifi

# Preserve sandbox / environment SSL certificate if present
if not os.environ.get("SSL_CERT_FILE"):
    os.environ["SSL_CERT_FILE"] = certifi.where()
if not os.environ.get("REQUESTS_CA_BUNDLE"):
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from eom_agent.workspace_service import (
    get_credentials,
    get_slides_service,
    get_drive_service,
    handle_generate_slide
)

FERRERO_FOLDER_ID = "1FdU3qyctloguhTWGj99ZtbayB1gg0p4R"
MISSION_NAME = "[Ferrero] Monitoring Platform for Agent Managers"
CLIENT = "Ferrero"

# High-fidelity realistic debrief data across 4 consulting personae
MULTI_PERSONA_PAYLOAD = {
    "executive": {
        "title": "Executive Summary",
        "card1": "Ferrero expanded multi-agent LLM systems across marketing and operations, creating operational visibility blind spots into latency and cloud token spend.",
        "card2": [
            "Centralized observability platform across multi-cloud agent fleets",
            "Real-time token cost allocation and consumption dashboards",
            "Executive alert routing and incident escalations"
        ],
        "card3": [
            "100% operational observability across active agent workflows",
            "-40% mean-time-to-resolution (MTTR) on model bottlenecks",
            "Quantified €120k projected annual API spend optimization"
        ],
        "card4": [
            "Scale telemetry ingestion to EMEA marketing automation fleets",
            "Institutionalize monthly agent reliability and ROI governance"
        ],
        "synthesis": "Delivered an enterprise-grade agent observability platform unifying LLM performance metrics, lowering MTTR by 40% and optimizing cloud token expenditures."
    },
    "technical": {
        "title": "Technical Architecture Blueprint",
        "card1": [
            "Heterogeneous agent frameworks across Python and LangChain",
            "OpenAI & Azure OpenAI rate limiting and unindexed log bursts",
            "Absence of distributed trace correlation across tool invocations"
        ],
        "card2": [
            "Azure Managed Grafana unified with Azure Log Analytics Workspace",
            "OpenTelemetry (OTel) Python SDK custom instrumentation",
            "Semantic conventions for LLM spans: prompt/completion token attributes"
        ],
        "card3": [
            "P95 latency dropped from 4.2s to 1.8s across agent execution pipelines",
            "99.9% telemetry pipeline uptime with zero lost trace events",
            "Sub-second trace indexing in Azure Log Analytics"
        ],
        "card4": [
            "Terraform modules for infrastructure-as-code deployment",
            "CI/CD regression test harness with GitHub Actions",
            "Grafana alerting rules connected to Slack and PagerDuty"
        ],
        "synthesis": "Architected an OpenTelemetry and Azure-native monitoring framework providing distributed tracing, P95 latency observability, and automated alerting."
    },
    "knowledge": {
        "title": "Internal Practice Knowledge & Lessons Learned",
        "card1": [
            "4-week agile sprint delivery framework",
            "Staffing ratio: 1 Senior Data Engineer + 1 AI Architect",
            "Bi-weekly stakeholder demo cycle driving rapid alignment"
        ],
        "card2": [
            "Packaged Artefact OTel Python wrapper library for agentic workflows",
            "Pre-configured Grafana dashboard JSON templates for LLM telemetry",
            "Automated BigQuery cost ingestion & billing projection script"
        ],
        "card3": [
            "Azure Cloud IAM role delays stalled early metric ingestion by 3 days",
            "Raw prompt logging initially triggered privacy risks, solved via PII masking filter"
        ],
        "card4": [
            "Pre-audit cloud IAM permissions in Week 1 before sprint kickoff",
            "Mandate PII sanitization filter at the OTel collector level for future GenAI missions"
        ],
        "synthesis": "Packaged reusable OTel agent monitoring assets and established clear governance guidelines for IAM prerequisites and client PII sanitization."
    },
    "referential": {
        "title": "Commercial Case Study & RFP Credentials (Sanitized)",
        "anonymizedClient": "A Global Tier-1 FMCG & Confectionery Leader",
        "brands": ["Nutella", "Kinder"],
        "card1": [
            "A Global Tier-1 FMCG Leader scaled autonomous GenAI agents across core business functions but lacked visibility into operational reliability, model errors, and escalating cloud AI costs.",
            "Mission-critical operations across flagship confectionary brand workflows required continuous uptime."
        ],
        "card2": [
            "Artefact architected and deployed an end-to-end Enterprise Agent Observability Hub combining OpenTelemetry instrumentation and Azure cloud monitoring.",
            "Established standardized L1/L2/L3 telemetry conventions and executive dashboards."
        ],
        "card3": [
            "-40% reduction in incident diagnosis and resolution time",
            "100% full-fleet visibility across multi-agent production systems",
            "25% cloud inference spend optimization via proactive bottleneck detection"
        ],
        "card4": [
            "Proven consulting expertise in production-grade GenAI agent observability",
            "Proprietary accelerator libraries enabling delivery in under 4 weeks",
            "Enterprise cloud compliance and PII governance frameworks"
        ],
        "synthesis": "Artefact delivered an end-to-end GenAI agent observability platform for a Tier-1 FMCG leader, cutting incident resolution time by 40% and optimizing AI cloud spend."
    }
}

SCRATCH_DIR = "/Users/ayrtonandre/.gemini/antigravity-cli/brain/19b5b6e1-1855-410e-af77-fb125ffb7499/scratch"
PERSONA_IMAGES = {
    "executive": os.path.join(SCRATCH_DIR, "grafana_slide_4_pic_1.png"),
    "technical": os.path.join(SCRATCH_DIR, "HLD.png"),
    "knowledge": os.path.join(SCRATCH_DIR, "Decision_Tree.png"),
    "referential": os.path.join(SCRATCH_DIR, "HLD.png")
}

def verify_live_generation():
    print(f"Generating 4-Slide Multi-Persona Deck with Embedded Deliverable Visuals in folder: {FERRERO_FOLDER_ID}...")
    res = handle_generate_slide(
        folder_raw=FERRERO_FOLDER_ID,
        mission_name=MISSION_NAME,
        card=MULTI_PERSONA_PAYLOAD,
        client=CLIENT,
        images=PERSONA_IMAGES
    )
    pres_id = res["presentationId"]
    pres_url = res["presentationUrl"]
    print(f"✅ Generated Presentation ID: {pres_id}")
    print(f"🔗 Presentation URL: {pres_url}")

    slides_svc = get_slides_service()
    pres = slides_svc.presentations().get(presentationId=pres_id).execute()
    slides = pres.get("slides", [])
    print(f"📊 Total Slides in Deck: {len(slides)}")
    assert len(slides) == 4, f"Expected 4 slides, got {len(slides)}"

    persona_names = ["Executive Sponsor", "Technical Blueprint", "Internal Knowledge", "Referential (Sanitized)"]
    for idx, slide in enumerate(slides):
        slide_text = ""
        has_image = False
        for pe in slide.get("pageElements", []):
            if "image" in pe:
                has_image = True
            if "shape" in pe and "text" in pe["shape"]:
                for te in pe["shape"]["text"].get("textElements", []):
                    if "textRun" in te:
                        slide_text += te["textRun"]["content"] + " "
        print(f"\n--- Slide {idx+1}: {persona_names[idx]} (ID: {slide.get('objectId')}, Has Image: {has_image}) ---")
        assert has_image, f"Slide {idx+1} ({persona_names[idx]}) is missing deliverable image!"
        lines = [l.strip() for l in slide_text.split("\n") if l.strip()]
        for line in lines[:6]:
            print(f"  {line}")

        # Assertions
        assert has_image, f"Slide {idx+1} ({persona_names[idx]}) is missing hero deliverable image!"
        if idx == 0:
            assert "EXECUTIVE SUMMARY:" in slide_text
            assert "Ferrero" in slide_text
        elif idx == 1:
            assert "TECHNICAL BLUEPRINT:" in slide_text
            assert "OpenTelemetry" in slide_text
            assert "Azure" in slide_text
        elif idx == 2:
            assert "PRACTICE CAPITALISATION:" in slide_text
            assert "OTel" in slide_text or "Grafana" in slide_text
        elif idx == 3:
            assert "COMMERCIAL CASE STUDY:" in slide_text
            assert "Ferrero" not in slide_text, f"CRITICAL: Leakage of client name 'Ferrero' on Slide 4!"
            assert "Nutella" not in slide_text, f"CRITICAL: Leakage of brand name 'Nutella' on Slide 4!"
            assert "A Global Tier-1 FMCG Leader" in slide_text
            assert "OpenTelemetry" in slide_text  # Tech terms preserved!

    print("\n" + "=" * 80)
    print("🎉 ALL LIVE MULTI-PERSONA SLIDE ASSERTIONS PASSED PERFECTLY!")
    print("=" * 80)

if __name__ == "__main__":
    verify_live_generation()
