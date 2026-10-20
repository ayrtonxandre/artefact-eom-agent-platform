#!/usr/bin/env python3
"""
Local ADK Runner for Artefact EOM Multi-Agent Pipeline.
Runs end-to-end mission closure with real-time execution event tracing.
"""
import os
import sys
import asyncio
from datetime import datetime

# Set GCP Vertex AI Environment Variables
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.environ["GOOGLE_CLOUD_PROJECT"] = "privategpt-437907"
os.environ["GOOGLE_CLOUD_LOCATION"] = "europe-west1"
os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "true"

SA_PATH = os.path.join(PROJECT_ROOT, "service_account.json")
if os.path.exists(SA_PATH):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = SA_PATH

DRIVE_TOKEN = os.path.join(PROJECT_ROOT, "drive_token.json")
if os.path.exists(DRIVE_TOKEN):
    os.environ["DRIVE_TOKEN_PATH"] = DRIVE_TOKEN

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from eom_agent.agent import root_agent

DEFAULT_FOLDER = "https://drive.google.com/drive/folders/1oqx6AT98K36xUOM2G_UYKBRGMfv_ub-U"
DEFAULT_EMAIL = "ayrton.andre@artefact.com"

async def run_eom_mission(folder_url: str = DEFAULT_FOLDER, lead_email: str = DEFAULT_EMAIL):
    print("=" * 70)
    print("🚀 Artefact EOM Autonomous Pipeline (ADK Local Runner)")
    print("=" * 70)
    print(f"Mission Folder : {folder_url}")
    print(f"Lead Email     : {lead_email}")
    print(f"Project        : {os.environ.get('GOOGLE_CLOUD_PROJECT')}")
    print(f"Model          : gemini-2.5-flash (Vertex AI)")
    print("=" * 70 + "\n")

    user_query = (
        f"Run the End of Mission automation for folder {folder_url} "
        f"and notify {lead_email}"
    )

    session_service = InMemorySessionService()
    runner = Runner(
        agent=root_agent,
        app_name="artefact_eom_pipeline",
        session_service=session_service
    )

    user_id = "mission_lead"
    session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    await session_service.create_session(
        app_name="artefact_eom_pipeline",
        user_id=user_id,
        session_id=session_id
    )

    content = types.Content(
        role="user",
        parts=[types.Part(text=user_query)]
    )

    print("🤖 Starting Mission Orchestrator...\n")
    final_response_text = ""

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content
    ):
        # Event logging for visibility
        if hasattr(event, "node_name") and event.node_name:
            print(f"[{event.node_name}]", end=" ", flush=True)

        func_calls = event.get_function_calls()
        for call in func_calls:
            print(f"\n⚙️  Tool Call: {call.name}")
            if hasattr(call, "args") and call.args:
                import json
                try:
                    print(f"    Args: {json.dumps(call.args, indent=2, default=str)}")
                except Exception:
                    print(f"    Args: {call.args}")

        func_responses = event.get_function_responses()
        for resp in func_responses:
            print(f"\n✔️  Tool Response received for {resp.name}")

        if hasattr(event, "content") and event.content and event.content.parts:
            for p in event.content.parts:
                if hasattr(p, "text") and p.text and not event.is_final_response():
                    print(f"\n💬 Thought/Draft: {p.text}\n")

        if event.is_final_response():
            if event.content and event.content.parts:
                final_response_text = "\n".join(
                    [p.text for p in event.content.parts if hasattr(p, "text") and p.text]
                )

    print("\n" + "=" * 70)
    print("📋 FINAL AGENT OUTPUT")
    print("=" * 70)
    print(final_response_text)
    print("=" * 70)

if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FOLDER
    email = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_EMAIL
    asyncio.run(run_eom_mission(folder, email))
