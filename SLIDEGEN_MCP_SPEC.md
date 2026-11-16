# Technical Specification: ATF Slidegen MCP Integration

## 1. Overview & Objective

The **Artefact EOM Agent Platform** currently generates multi-persona consultant presentations directly via the Google Slides API (`engine: "google_slides"`) using the Artefact 2025 Master Template.

This specification details the integration of the internal Artefact Slide Generator MCP (`atf-slide-generator`) as an alternative generation engine (`engine: "atf_slidegen"`).

```
                      ┌──────────────────────────────────────┐
                      │    handle_generate_slide(..., engine)│
                      └──────────────────┬───────────────────┘
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 │                                               │
                 ▼                                               ▼
   [engine == "google_slides"]                      [engine == "atf_slidegen"]
   Official 2025 Master Template                    ATF Slidegen MCP Client
   (Direct Google Slides API)                       (HTTP / SSE Transport)
   4 Personae (Exec, Tech, Know, Ref)               https://slidegen-mcp-.../mcp
                 │                                               │
                 │                                               │ (Fallback if error)
                 │                                               ▼
                 └───────────────────────────────► Final Google Slides Deck
```

---

## 2. Server & Authentication Details

- **MCP Endpoint**: `https://slidegen-mcp-787782215301.europe-west1.run.app/mcp`
- **Frontend App**: `https://slidegen-frontend-q22gtq7zla-ew.a.run.app/`
- **Transport**: HTTP / SSE (Server-Sent Events) or JSON-RPC 2.0 over HTTP POST.
- **Authentication**:
  Because the MCP runs on Google Cloud Run in project `787782215301`, requests require an OIDC ID token with audience `https://slidegen-mcp-787782215301.europe-west1.run.app`:
  ```python
  from google.auth.transport.requests import Request
  import google.oauth2.id_token

  def get_mcp_auth_token(audience: str = "https://slidegen-mcp-787782215301.europe-west1.run.app") -> str:
      auth_req = Request()
      return google.oauth2.id_token.fetch_id_token(auth_req, audience)
  ```

---

## 3. Implementation Steps

### Step 1: Add MCP Client (`eom_agent/slidegen_mcp_client.py`)
Create a client module encapsulating:
- Authentication token retrieval.
- Tool discovery (`tools/list`).
- Presentation generation execution (`tools/call`).
- Formatting the multi-persona prompt and mission context so Slidegen generates the requested slides in the target Google Drive folder.

### Step 2: Route in `workspace_service.py`
In `handle_generate_slide`:
```python
def handle_generate_slide(
    folder_id: str,
    mission_name: str,
    card_data: Any,
    client: Optional[str] = None,
    engine: str = "google_slides",
    ...
) -> Dict[str, Any]:
    if engine == "atf_slidegen":
        try:
            return call_slidegen_mcp_engine(folder_id, mission_name, card_data, client)
        except Exception as exc:
            logger.warning(f"Slidegen MCP failed ({exc}). Falling back to native Google Slides engine.")
            # Fallback cleanly to native template
    
    # Native Google Slides engine execution...
```

### Step 3: Update API Models & Endpoints (`service/main.py`)
Add `engine` to request schemas:
```python
class GenerateSlideRequest(BaseModel):
    ...
    engine: Optional[str] = "google_slides"  # 'google_slides' | 'atf_slidegen'

class WrapupMissionRequest(BaseModel):
    ...
    engine: Optional[str] = "google_slides"
```

### Step 4: Regenerate OpenAPI Specs
Export updated OpenAPI schema:
```bash
python -c "import json; from service.main import app; open('openapi.json', 'w').write(json.dumps(app.openapi(), indent=2))"
```

### Step 5: Unit & Contract Tests (`tests/`)
Add tests in `tests/test_service_contracts.py`:
- Test `GenerateSlideRequest` with `engine="atf_slidegen"`.
- Mock MCP client responses (`success`, `timeout`, `fallback to native`).
- Verify offline execution remains 100% green without network dependency.

---

## 4. Acceptance Criteria

1. Running `pytest` continues to pass 100% offline.
2. If `engine="atf_slidegen"` is requested and network/credentials allow, the MCP generates the deck and moves it to `folder_id`.
3. If `engine="atf_slidegen"` encounters an error or timeout, the pipeline falls back automatically to native `google_slides` without breaking the consulting wrap-up.
4. The Swagger documentation at `/docs` reflects the new `engine` parameter.
