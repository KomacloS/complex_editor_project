# Complex‑Editor

**Complex‑Editor** is a Python tool that lets engineers create, edit and export *complex device* definitions for Seica / VIVA ATE systems.

* ⚙️  Build new complexes by combining existing VIVA macros, pins and parameters  
* 📎  View the component datasheet side‑by‑side while you work  
* 🗄️  Store complexes in a searchable SQLite library  
* 📤  Export selected complexes straight into any VIVA program MDB with automatic backup & diff  
* 🧠  Road‑map: AI assistant to extract pin maps and parameters directly from the PDF datasheet

## Quick start (dev mode)

```bash
git clone https://github.com/your‑org/complex‑editor.git
cd complex‑editor

# optional: start fresh
rm -rf .venv                 # PowerShell: Remove-Item -Recurse -Force .venv
py -3.12 -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
python -m complex_editor.cli --help
python ui_skeleton.py          # works from project root without PYTHONPATH hacks
```

## Directory layout

```
internal/            # packaged runtime payload (config, exe, etc.)
src/complex_editor/   # application packages
tests/                # pytest unit tests
examples/             # demo MDB & PDF (not committed)
```

## CE Bridge: Traceable Logging and Admin Log Retrieval

- Logging directory: controlled by `CE_LOG_DIR`.
  - Defaults: Windows -> `%LOCALAPPDATA%\CE\logs`; Linux -> `/var/log/ce`.
- Other env vars:
  - `CE_LOG_LEVEL` (default `INFO`)
  - `CE_LOG_JSON` (default `true`; set to `false` for plain text)
  - `CE_LOG_MAX_BYTES` (default `10485760`)
  - `CE_LOG_BACKUP_COUNT` (default `5`)

Every request carries a `X-Trace-Id` header. If the client doesn't send one, the bridge generates a UUID4 and returns it in the response header. All log lines include `trace_id`.

On startup, the bridge logs the resolved logs directory and prints a sample curl to fetch logs for a trace id.

To retrieve logs and a nearby stacktrace for a specific request trace id:

```
curl -s -H "Authorization: Bearer <TOKEN>" \
  http://<HOST>:<PORT>/admin/logs/<TRACE_ID>
```

Response example:

```
{
  "trace_id": "...",
  "hits": [
    {"file": ".../ce_bridge.log", "line": 120, "context_before": ["..."], "line_text": "...", "context_after": ["..."]}
  ],
  "stacktrace": "Traceback (most recent call last):\n  File ...\nTypeError: ..."
}
```

### Insert Debug Logging

- During detCompDesc inserts, the DB layer logs at INFO using logger `complex_editor.db.mdb_api.insert`:
  - table name, foreign key, column list, and a preview of coerced values
  - on success, the new `@@IDENTITY`
- Set overall log level via `CE_LOG_LEVEL` (e.g., `INFO` or `DEBUG`). JSON logs enabled by default (`CE_LOG_JSON=true`).

## Offline MDB tools

- Dump table schema:
  - Command: `python tools/dump_mdb_schema.py --mdb PATH --table detCompDesc`
  - Prints JSON of column name/type/nullable/size/precision.

- Reproduce a single INSERT into detCompDesc:
  - Prepare a JSON file with `{ "cols": [...], "vals": [...] }` as produced by `SubComponent._flatten`.
  - Command: `python tools/repro_insert_detcompdesc.py --template PATH\\to\\template.mdb --target PATH\\to\\out.mdb --json payload.json`
  - Shows per-column Python type and value, runs the parameterized INSERT, and prints `exc.args` if `pyodbc.DataError` occurs.

### Headless Exports

- By default the bridge rejects `/exports/mdb` requests when running without the desktop UI.
- Override per run with `CE_ALLOW_HEADLESS_EXPORTS=1` (environment) or `python -m ce_bridge_service.run --allow-headless-exports` (CLI).
- When disabled, responses include `reason=bridge_headless`, `status=503`, and `allow_headless=false`; the same booleans are exposed via `GET /admin/health`.
- Optional: set `CE_TEMPLATE_MDB` to an absolute path for the export template; otherwise the bridge uses `complex_editor/assets/Empty_mdb.mdb`.
- When the headless saver falls back to the pure exporter you will see `Resolved template_path=<...>` followed by `headless export: fallback_to_export_pn_to_mdb template=<path>` in the logs.
