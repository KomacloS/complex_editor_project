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
- When the bridge is created with a non-empty bearer token (via CLI or `CE_AUTH_TOKEN`), **all routes except `/admin/health`** require:
  ```
  Authorization: Bearer <token>
  ```
- `/admin/health` will also honor the token; requests without it receive `401/403`.
- Always send `X-Trace-Id`; the bridge generates one when absent and echoes it back as `trace_id` in responses.

### Tracing & Logs
- Every request accepts/returns a trace id via the `X-Trace-Id` header. If you don’t send one, the bridge will generate it.
- You can fetch log lines correlated to a trace id:
  - `GET /admin/logs/{trace_id}` (see Admin endpoints below)

### Key environment variables
| Name | Purpose |
| --- | --- |
| `CE_MDB_PATH` | Absolute path to the Complex Editor main database (required). |
| `CE_AUTH_TOKEN` | Bearer token expected from clients; must match BOM_DB configuration. |
| `CE_ALLOW_HEADLESS_EXPORTS` | When truthy (`1`, `true`, `yes`, `on`), allows `/exports/mdb` while the desktop UI is not present. Can also be granted programmatically when creating the app. |
| `CE_TEMPLATE_MDB` | Absolute/expandable path to the MDB template used for exports when the request body omits `template_path`. |
| `CE_LOG_LEVEL` | Log level for bridge, uvicorn, and Complex Editor loggers. Defaults to `WARNING`. |
| `CE_LOG_FILE` | Full path to a writable log file. Overrides all other log destinations. |
| `CE_LOG_DIR` | Directory that should contain `bridge.log` when `CE_LOG_FILE` is not set. |
| `CE_DEBUG` | When truthy, enables debug logging (equivalent to `CE_LOG_LEVEL=DEBUG`) and adds a console handler in addition to file logging. |

## Admin endpoints
### `GET /admin/health`
Returns readiness information.
```json
{
  "ready": true,
  "headless": true,
  "allow_headless": true,
  "reason": "ok",
  "trace_id": "echoed-trace-id"
}
```
Rules:
- `ready:true` only after the bridge loads `CE_MDB_PATH` and exports are permitted. If the app is headless but exports are disabled, respond with:
  ```json
  {
    "ready": false,
    "headless": true,
    "allow_headless": false,
    "reason": "exports_disabled_in_headless_mode"
  }
  ```
- `trace_id` echoes `X-Trace-Id` or a generated value so callers can correlate responses with logs.

### `GET /admin/logs/{trace_id}`
Returns recent log lines correlated to `trace_id`. Requires bearer token if `auth_token` was provided at startup.

### `POST /admin/shutdown`
Requests an orderly shutdown. Requires bearer token if `auth_token` was provided at startup. Include `{"force": 1}` in the JSON body to bypass graceful safeguards when an immediate shutdown is required. Returns `204 No Content` when the shutdown signal is accepted.

### `GET /state`
Minimal process snapshot used by the desktop shell:
```json
{ "unsaved_changes": false }
```

## Endpoints
### `GET /complexes/search`
Search the CE database by part number or alias. Returns a list of `{ "id": "5087", "pn": "..." }` records. Supports `limit` (default 20, max 200).

### `GET /complexes/{id}`
Return the detailed CE record for the given ID. Responds with HTTP 404 when the ID is not present.

### `POST /exports/mdb` *(subset export)*
Legacy export endpoint that writes a subset MDB for the supplied component IDs. Remains for desktop integrations; new automation should prefer `/ce/export`.

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
  1. Payload value (when provided).
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

#### Error responses
| HTTP status | `reason` | Meaning |
| --- | --- | --- |
| 503 | `bridge_headless` | Headless exports are disabled (`allow_headless_exports` is false). |
| 409 | `template_missing_or_incompatible` | Template file missing or empty. Payload includes `template_path`. |
| 500 | `db_engine_error` | Database coercion failed (surface of `DataMismatch`). Includes `detail`. |
| 409 | `no_matches` | Provided IDs/PNS didn’t match anything in the source DB. |
| 409 | `empty_selection` | After normalization, no IDs were left to export. |
| 409 | `outdir_unwritable` | Destination directory not writable. Includes `errno` and `detail`. |
| 404 | `comp_ids_not_found` | None of the provided IDs resolved. Payload includes `missing`. |

### `POST /ce/export`
Primary automation endpoint used by BOM_DB. Produces both an Access MDB and a CSV status report.

#### Request body
```json
{
  "trace_id": "echo-of-X-Trace-Id",
  "out_dir": "C:/exports",
  "complex_ids": ["5087", "5089"],
  "options": { "overwrite": true }
}
```

#### Responses
- `SUCCESS`: export completed (`mdb_path`, `report_csv`, `exported`, `skipped`).
- `PARTIAL_SUCCESS`: export completed with skips; includes `skip_reasons` summarizing why entries were ignored.
- `FAILED_INPUT`: invalid request (e.g., unwritable out_dir). `reason` explains the input failure.
- `FAILED_BACKEND`: recoverable CE issue (e.g., `template_missing_or_incompatible`). Include `trace_id` for support.
- `RETRY_LATER`: bridge warming up (`reason: "ce_warming_up"`).
- `RETRY_WITH_BACKOFF`: transient CE DB contention (`reason: "db_locked"`).

#### CSV report
- Written to `<out_dir>/CE/report.csv`.
- Columns: `pn,ce_complex_id,status,reason` with `status` in `{exported,skipped}`.

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

### Trigger a BOM export
```bash
curl -X POST http://127.0.0.1:8000/ce/export \
  -H "Authorization: Bearer $CE_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Trace-Id: $(uuidgen)" \
  -d '{"out_dir":"C:/exports","complex_ids":["5087","5089"],"options":{"overwrite":true}}'
```
The response includes aggregate counts plus `mdb_path` and `report_csv`. Examine `C:/exports/CE/report.csv` for per-ID status.

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
