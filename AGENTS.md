# Ponytail: EOM Agent Platform Ruleset (Lazy Senior Dev Mode)

You are working on **Artefact EOM Agent Platform**, an autonomous end-of-mission lifecycle service orchestrating Google Workspace tools (Drive, Docs, Slides, Sheets, Gmail) and BigQuery for mission debriefs and audit generation.
The best code is the code never written. Solve problems with the minimum necessary code while fiercely protecting OpenAPI contracts, security boundaries, and Google Cloud Agent Platform integration.

## EOM Core Invariants
1. **OpenAPI & Pydantic Contract Stability (Never Break)**:
   - `service/main.py` exposes the HTTP tool interface consumed by Google Cloud Agent Platform and Vertex AI Agent Designer.
   - Dual-naming conventions (camelCase for OpenAPI / Google Cloud Agent Platform and snake_case for Python) must be preserved on all Pydantic request models.
   - Never rename, delete, or break fields declared in `openapi.yaml`, `openapi.json`, or `toolspec.json`.
2. **Single Source of Truth for Workspace Services**:
   - Workspace automation routines (Drive file search, Docs creation, Slides generation, Sheets audits, Gmail delivery, Central Status Tracker logging) live exclusively in `eom_agent/workspace_service.py`.
   - `service/main.py` is the HTTP routing and presentation adapter layer. It must import routines from `eom_agent.workspace_service` rather than re-declaring them.
3. **Cloud Run & GCP Security Boundaries**:
   - **No Hardcoded Absolute Paths**: Use environment variables (`DRIVE_TOKEN_JSON`, `DRIVE_TOKEN_PATH`, `GCP_PROJECT`), relative paths, or Google Application Default Credentials (`google.auth.default()`).
   - **No Insecure SSL Monkey-Patching**: Never globally disable TLS validation (`ssl._create_unverified_context` is strictly prohibited). Use `certifi` bundles.
   - **Credential Hygiene**: Never commit Google OAuth tokens (`drive_token.json`), client secrets, or Service Account JSON files into git.
4. **Fast Offline Verification (Mandatory)**:
   - Offline contract and unit tests live in `tests/test_service_contracts.py`.
   - Validate Pydantic schema parsing, Google Drive ID extraction, and HTML templating without requiring active GCP network credentials:
     ```bash
     python3 -m unittest discover tests
     ```

## Ponytail Execution Ladder
1. **Does this helper need to exist?** Favor standard Python modules and Google API client SDKs over custom abstraction frameworks.
2. **Already in `workspace_service.py` or `bigquery_service.py`?** Reuse existing business logic and helpers.
3. **Protect Cloud Run build packaging**: Any changes to dependencies must reflect in both `eom_agent/requirements.txt` and `service/requirements.txt`.
4. **Tag intentional shortcuts**: Tag any necessary temporary workaround with `# shortcut: <limit>, <when to upgrade>`.

End every reply with 1–2 lines: what was skipped or not checked, and any risk the user should know.
