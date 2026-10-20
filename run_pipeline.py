#!/usr/bin/env python3
"""Artefact End-of-Mission (EOM) Remote Pipeline Runner

Invokes the deployed Vertex AI Agent Engine ('artefact-eom-pipeline') in europe-west1.
"""

import os
import sys
import json
import argparse
import vertexai

# Ensure credentials are set
DEFAULT_SA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "service_account.json")
if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and os.path.exists(DEFAULT_SA_PATH):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = DEFAULT_SA_PATH

PROJECT_ID = "privategpt-437907"
LOCATION = "europe-west1"
ENGINE_RESOURCE_NAME = "projects/981078856173/locations/europe-west1/reasoningEngines/4533231465739059200"


def invoke_remote_agent(message: str, user_id: str = "consultant_lead"):
    """Sends a query to the remote Vertex AI Reasoning Engine and streams output."""
    client = vertexai.Client(project=PROJECT_ID, location=LOCATION)
    
    print(f"\n🚀 Connecting to Vertex AI Agent Engine: {ENGINE_RESOURCE_NAME}")
    print(f"👤 User ID: {user_id}")
    print(f"💬 Prompt: {message}\n" + "=" * 70 + "\n")
    
    stream = client.agent_engines._stream_query(
        name=ENGINE_RESOURCE_NAME,
        config={
            "class_method": "stream_query",
            "input": {
                "message": message,
                "user_id": user_id
            }
        }
    )
    
    for chunk in stream:
        if hasattr(chunk, "body"):
            try:
                data = json.loads(chunk.body)
                author = data.get("author", "Agent")
                
                # Check for tool calls or function calls
                actions = data.get("actions", {})
                parts = data.get("content", {}).get("parts", [])
                
                for p in parts:
                    if "text" in p and p["text"]:
                        print(f"[{author}]:\n{p['text']}\n")
                    elif "function_call" in p:
                        fc = p["function_call"]
                        print(f"🛠️  [{author} -> Tool Call: {fc.get('name')}]")
                        print(f"    Args: {json.dumps(fc.get('args', {}), indent=2)}")
                    elif "function_response" in p:
                        fr = p["function_response"]
                        print(f"✅  [{author} <- Tool Result: {fr.get('name')}]")
            except Exception as e:
                print(f"[Raw Stream Chunk]: {chunk.body}")


def main():
    parser = argparse.ArgumentParser(description="Artefact EOM Cloud Agent Runner")
    parser.add_argument("--folder", type=str, help="Google Drive folder URL or ID", default=None)
    parser.add_argument("--email", type=str, help="Consultant/Lead email for Gmail notification", default="ayrton.andre@artefact.com")
    parser.add_argument("--message", type=str, help="Custom message for the agent", default=None)
    parser.add_argument("--user", type=str, help="User identifier", default="ayrton.andre")

    args = parser.parse_args()

    if args.message:
        prompt = args.message
    elif args.folder:
        prompt = (
            f"Run the complete End of Mission (EOM) pipeline for project folder {args.folder}. "
            f"Generate the executive Google Slides one-pager, perform the security & confidentiality audit "
            f"into Google Sheets, and notify {args.email} upon completion."
        )
    else:
        # Default prompt if no argument provided
        prompt = "Hello! Please present your role and how you assist Artefact teams during mission handovers."

    invoke_remote_agent(message=prompt, user_id=args.user)


if __name__ == "__main__":
    main()
