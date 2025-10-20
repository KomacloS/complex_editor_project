# Complex Editor Bridge API

## Overview & Quickstart
The Complex Editor (CE) Bridge exposes a FastAPI service that coordinates headless exports from a running Complex Editor instance. It can run alongside the desktop application or in a headless export worker. The public surface is limited to a small set of endpoints that report bridge status and trigger MDB exports.

Explore the API via interactive OpenAPI docs at `http://127.0.0.1:8000/docs` (Swagger) or `http://127.0.0.1:8000/redoc` once the service is running.

### Run from sources
1) Create a Python 3.12 virtual environment and install dependencies:
   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2) Start the bridge (pick one):

   **A. Minimal runner (uses `CE_MDB_PATH` env)**
   ```bash
   # set the path to your data MDB
   export CE_MDB_PATH="C:/Users/You/ComplexBuilder/main_db.mdb"
   export CE_ALLOW_HEADLESS_EXPORTS=1   # optional, for headless testing
   python - <<'PY'
   import os, uvicorn
   from pathlib import Path
   from ce_bridge_service.app import create_app
   app = create_app(
       get_mdb_path=lambda: Path(os.environ["CE_MDB_PATH"]),
       allow_headless_exports=bool(os.environ.get("CE_ALLOW_HEADLESS_EXPORTS"))
   )
   uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
   PY
   ```

   **B. Your own wrapper / factory**
   If you already have a runner that passes `get_mdb_path`, you can keep using it.
   > Note: calling `uvicorn ce_bridge_service.app:create_app --factory` without arguments will fail because `create_app` requires `get_mdb_path`.

### Authentication
- If the bridge is created with a non-empty `auth_token`, **admin routes** require:
  ```
  Authorization: Bearer <token>
  ```
- Public routes (like `/exports/mdb`) remain open unless you add your own dependency.

### Tracing & Logs
- Every request accepts/returns a trace id via the `X-Trace-Id` header. If you don’t send one, the bridge will generate it.
- You can fetch log lines correlated to a trace id:
  - `GET /admin/logs/{trace_id}` (see Admin endpoints below)

### Key environment variables
| Name | Purpose |
| --- | --- |
| `CE_ALLOW_HEADLESS_EXPORTS` | When truthy (`1`, `true`, `yes`, `on`), allows `/exports/mdb` while the desktop UI is not present. Can also be granted programmatically when creating the app. |
| `CE_TEMPLATE_MDB` | Absolute/expandable path to the MDB template used for exports when the request body omits `template_path`. |
| `CE_LOG_LEVEL` | Log level for bridge, uvicorn, and Complex Editor loggers. Defaults to `WARNING`. |
| `CE_LOG_FILE` | Full path to a writable log file. Overrides all other log destinations. |
| `CE_LOG_DIR` | Directory that should contain `bridge.log` when `CE_LOG_FILE` is not set. |
| `CE_DEBUG` | When truthy, enables debug logging (equivalent to `CE_LOG_LEVEL=DEBUG`) and adds a console handler in addition to file logging. |

## Admin endpoints
### `GET /admin/health`
Returns readiness information. Response payload:
```json
{
  "ready": true,
  "headless": true,
  "allow_headless": false
}
```

### `GET /admin/logs/{trace_id}`
Returns recent log lines correlated to `trace_id`. Requires bearer token if `auth_token` was provided at startup.

### `POST /admin/shutdown`
Requests an orderly shutdown. Requires bearer token if `auth_token` was provided at startup. Include `{"force": 1}` in the JSON body to bypass graceful safeguards when an immediate shutdown is required. Returns `{ "ok": true }` when the shutdown signal is accepted.

## Endpoints
### `POST /exports/mdb`
Triggers an MDB export using a list of Complex Editor component IDs.

#### Request body
```json
{
  "comp_ids": [1001, 1002],
  "out_dir": "C:/exports",
  "mdb_name": "bom.mdb",
  "template_path": "C:/templates/custom.mdb"  // optional
}
```

- `comp_ids`: integers or strings convertible to integers. Duplicates and non-positive values are ignored.
- `out_dir`: absolute path (UNC and Windows-style paths supported). Created if missing.
- `mdb_name`: file name ending in `.mdb` (no path separators).
- `template_path` (optional): absolute path to a valid MDB template. Template source precedence:
  1. Payload `template_path` (when provided in the request).
  2. `CE_TEMPLATE_MDB` environment variable (if set).
  3. Packaged asset `complex_editor.assets/Empty_mdb.mdb`.

#### Success response (HTTP 200)
```json
{
  "ok": true,
  "export_path": "C:/exports/bom.mdb",
  "exported_comp_ids": [1001, 1002],
  "resolved": [
    { "pn": "SN74AHC1G08DBVR", "comp_id": 1001 },
    { "pn": "SN74...",         "comp_id": 1002 }
  ],
  "unlinked": [],
  "missing": []
}
```
- `resolved`: component IDs (and their part numbers) that were located and exported.
- `unlinked`: component IDs that were valid but lacked linked data (rare; returned for completeness).
- `missing`: IDs that could not be resolved. When some IDs are missing but at least one is exported, the call succeeds (HTTP 200) and `missing` contains the rejected IDs. A 404 with `comp_ids_not_found` is only returned when every requested ID is missing.

#### Error responses
| HTTP status | `reason` | Shape |
| --- | --- | --- |
| 503 | `bridge_headless` | Headless exports are disabled. Payload includes `allow_headless` and `status`. |
| 409 | `template_missing_or_incompatible` | Template file missing or empty. Payload includes `template_path` of the failing file. |
| 500 | `db_engine_error` | Database coercion failed (surface of `DataMismatch`). Payload includes `detail` message from Access. |
| 409 | `no_matches` | Provided PNs/IDs didn’t match anything in the source DB (with at least some unknowns). |
| 409 | `empty_selection` | After normalization, the export set was empty. |
| 409 | `outdir_unwritable` | Output directory could not be created or written. Payload includes `out_dir`, `errno`, and `detail`. |
| 404 | `comp_ids_not_found` | None of the provided IDs resolved. Payload includes the `missing` list. |

Example payloads:
```json
{
  "reason": "bridge_headless",
  "status": 503,
  "allow_headless": false,
  "trace_id": "52a9d23d-6a4a-4c7b-86e3-0cbdb4cd3c7a"
}
```
```json
{
  "reason": "db_engine_error",
  "detail": "detCompDesc insert failed: 22018 type mismatch",
  "trace_id": "8e9da964-5467-4f83-96d3-f07b0a6131a3"
}
```
```json
{
  "reason": "comp_ids_not_found",
  "detail": "No valid comp_ids to export.",
  "missing": ["9001", "9002"],
  "trace_id": "4d68f04c-44b6-4031-9b5d-2fbc9e314031"
}
```

## Logging
- **Default location**
  - Windows: `%LOCALAPPDATA%/CE/logs/bridge.log`
  - macOS/Linux: `~/.local/share/ce/logs/bridge.log`
- Logging always uses a rotating file handler (5 MB max, 3 backups). If the file cannot be created, the bridge falls back to console logging and emits a warning at startup.
- Override the destination by setting `CE_LOG_FILE` (preferred) or `CE_LOG_DIR` before the app starts.
- Adjust verbosity with `CE_LOG_LEVEL`. Set `CE_DEBUG=1` (or any truthy value) to enable debug-level messages, including development markers such as template resolution, exporter fallbacks, and insert previews. These debug markers stay hidden at the default `WARNING` level.

## Examples
### Export a single component
```bash
curl -X POST http://127.0.0.1:8000/exports/mdb \
  -H "Content-Type: application/json" \
  -d '{"comp_ids": [5087], "out_dir": "C:/exports", "mdb_name": "bom.mdb"}'
```

### Export with mixed valid and missing IDs
```bash
curl -X POST http://127.0.0.1:8000/exports/mdb \
  -H "Content-Type: application/json" \
  -d '{"comp_ids": [5087, 9999], "out_dir": "C:/exports", "mdb_name": "partial.mdb"}'
```
Response includes `missing: ["9999"]` while returning HTTP 200.

### Use a payload-provided template
```bash
curl -X POST http://127.0.0.1:8000/exports/mdb \
  -H "Content-Type: application/json" \
  -d '{"comp_ids": [5087], "out_dir": "C:/exports", "mdb_name": "custom.mdb", "template_path": "C:/templates/bridge_template.mdb"}'
```

### Windows path quirks
When invoking from PowerShell, escape backslashes or wrap arguments in double quotes:
```powershell
curl -Method POST http://127.0.0.1:8000/exports/mdb `
  -Headers @{"Content-Type"="application/json"} `
  -Body '{"comp_ids":[5087],"out_dir":"C:\\Exports With Spaces","mdb_name":"bom.mdb"}'
```

### Enabling debug logging temporarily
```bash
export CE_DEBUG=1
export CE_LOG_LEVEL=DEBUG
export CE_MDB_PATH="C:/Users/You/ComplexBuilder/main_db.mdb"
python - <<'PY'
import os, uvicorn
from pathlib import Path
from ce_bridge_service.app import create_app

app = create_app(
    get_mdb_path=lambda: Path(os.environ["CE_MDB_PATH"])
)

uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
PY
```

Debug logs include template resolution, fallback paths, coercion previews, and trace-aware access lines.

## Extending the API (for contributors)
- Models & shapes: add request/response Pydantic models in src/ce_bridge_service/models.py. Keep field names snake_case and response envelopes stable.
- Error envelope: use the existing _error_response(...) helper to return {"reason": ..., "detail": ..., "trace_id": ...} with an appropriate HTTP status. Prefer adding a new reason over changing existing ones.
- Partial success pattern: when returning mixed results, keep HTTP 200 and include a missing array. Only return 404 `comp_ids_not_found` if all inputs are missing.
- Tracing: read `X-Trace-Id` if present, otherwise generate one and attach to logs/events; return it in all error responses.
- Logging: default levels should be `WARNING` or higher. Use `DEBUG` for verbose markers (coercions, template resolver, fallback paths). Don’t log request bodies.
- Tests: add endpoint tests under `tests/`, and keep `ce312_api_smoke_tests.sh` green (expect `PASS: 5`, `FAIL: 0`).
