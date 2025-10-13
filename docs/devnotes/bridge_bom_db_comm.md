# Bridge ↔️ BOM_DB Communication Overview

The bridge now keeps a live readiness picture of its connection to the BOM_DB
(MDB) so UI clients no longer have to trigger `/selftest` before the service
is usable. This document captures how that communication happens and which
FastAPI endpoints surface the state.

## Startup and Background Diagnostics

When the bridge process starts we schedule an asynchronous readiness task from
the FastAPI startup event. The task performs the same diagnostics that were
previously only reachable through `/selftest`:

1. Resolve the MDB path from configuration.
2. Confirm the path exists and is a file.
3. Open the MDB with the configured factory and run a simple
   `SELECT PK_MASTER FROM MASTER_T` query to prove read access.
4. Record bookkeeping information such as a SHA-256 signature of the resolved
   path and whether authentication is enabled.

Each step contributes an entry in `app.state.last_ready_checks`. If any step
fails, we keep the service in the warming-up (HTTP 503) state and aggregate the
failing check details into `app.state.last_ready_error`. A success flips the
bridge to ready, logging the transition with host/port/auth metadata.

These diagnostics run without blocking inbound HTTP handlers because they
execute inside a background task guarded by an `asyncio.Lock`. If the MDB path
changes later (for example after a UI settings edit) the bridge clears the last
result, returns to the warming-up state, and reschedules the same background
checks with the new path.

## Request Handling

* **`GET /health`** – Returns `503` with `{ "ok": false, "reason": ... }` until
  the background checks mark the bridge ready. Once ready, the endpoint exposes
  the resolved MDB path, host, port, and auth requirement.
* **`GET /state`** – Always returns the readiness flag, the aggregated error
  message, and the raw diagnostics list so the UI can display detailed feedback
  about why the MDB connection is unavailable.
* **`POST /selftest`** – Still triggers the diagnostics on demand for manual or
  UI-driven revalidation, but because the result is stored in application
  state, concurrent `/health` requests continue to respond immediately with the
  last known readiness result instead of blocking for the new check.

## Regular BOM_DB Queries

Once ready, all functional endpoints obtain a fresh MDB connection from the
same `mdb_factory` when needed. Searches, detail lookups, and wizard-assisted
create flows open the MDB, issue the relevant SQL queries (or fall back to
simpler ones if alias metadata is unavailable), and close the connection.

This design ensures the bridge notices connectivity problems quickly, exposes
clear diagnostics to the UI, and remains responsive even while BOM_DB checks
are executing.
