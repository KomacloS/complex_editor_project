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

## BOM_DB search analysis and linking workflow

### Server-side match classification

`GET /complexes/search` accepts an optional `analyze=true` query parameter. When
present the bridge classifies every hit according to how it matched the
user-supplied part number:

| `match_kind`        | Meaning                                                |
| ------------------- | ------------------------------------------------------ |
| `exact_pn`          | PN case-insensitively equals the user input.           |
| `exact_alias`       | Alias case-insensitively equals the user input.        |
| `normalized_pn`     | Normalized input equals the normalized PN.             |
| `normalized_alias`  | Normalized input equals a normalized alias.            |
| `like`              | Fallback `LIKE` match (no normalization alignment).    |

Each result also includes:

- `reason`: human-readable explanation (`"Normalized input matched alias (removed punctuation, ignored suffix '/TP')"`).
- `normalized_input`: canonical form of the caller input after normalization.
- `normalized_targets`: canonical PN/alias forms that produced the match (may be empty).
- `rule_ids`: ordered normalization rule identifiers fired for the input.

Additional semantics:

- Normalized matches require a non-empty normalized input. Inputs that collapse
  to nothing after suffix/punctuation stripping (e.g., `-TR`) are only eligible
  for `like` matches.
- `reason` explains whether the `LIKE` came from the canonical PN or an alias
  and may mention target-side transforms. Only input-side rules are reported via
  `rule_ids` so the normalized input remains auditable.
- Results are ordered by match quality (`exact_*` → `normalized_*` → `like`) and
  then fall back to the database’s natural ordering for deterministic pagination.
- Wildcard-only or punctuation-only inputs are rejected early with the same
  `400` used for empty part numbers to avoid runaway table scans.

Example without analysis:

```http
GET /complexes/search?pn=SN74&limit=5

[
  { "id": 5087, "pn": "SN74AHC1G08DBVR", "aliases": ["SN74AHC1G08DR"] }
]
```

Example with analysis enabled:

```http
GET /complexes/search?pn=sn74ahc1g08-tr&analyze=true

[
  {
    "id": 5087,
    "pn": "SN74AHC1G08DBVR",
    "aliases": ["SN74AHC1G08DR"],
    "match_kind": "normalized_alias",
    "reason": "Normalized input matched alias (uppercased input, ignored suffix '-TR', removed punctuation)",
    "normalized_input": "SN74AHC1G08",
    "normalized_targets": ["SN74AHC1G08"],
    "rule_ids": [
      "rule.case_fold",
      "rule.strip_suffix.-TR",
      "rule.strip_punct"
    ]
  }
]
```

When `analyze` is omitted or `false` the payload is identical to previous
releases so legacy clients remain unaffected.

### Normalization ruleset

The normalization pipeline is configurable through `pn_normalization` in
`complex_editor.yml` (or the default config):

```yaml
pn_normalization:
  case: "upper"
  remove_chars: [" ", "-", "_", ".", "/", "–", "—", "\u00A0"]
  ignore_suffixes: ["-TR", "-T", "-REEL", "/TP", "-BK"]
```

Rules fire in order (case fold → suffix stripping → punctuation removal) and
produce rule identifiers such as `rule.case_fold` or
`rule.strip_suffix.-TR`. Suffix tokens are evaluated in the order listed and may
be removed sequentially (longest-first ordering is recommended to avoid
accidental partial matches). The bridge logs the active configuration once
during startup and exposes the ruleset version through `/state` as
`features.normalization_rules_version` (currently `"v1"`).

Support staff can inspect the live rules via `GET /admin/pn_normalization`,
which returns both the configuration and the advertised rules version for
dashboard integrations.

### Feature flags

`GET /state` now returns:

```json
"features": {
  "export_mdb": true,
  "search_match_kind": true,
  "normalization_rules_version": "v1"
}
```

Clients should check `search_match_kind` before requesting analysis. Older
bridges report `false` and will ignore the `analyze` toggle, preserving
backward compatibility. `export_mdb` reflects whether exports are currently
permitted given readiness and the headless policy (headless mode without
override reports `false`).

### Telemetry & logging

Search analysis emits structured logs under the `search_analyze` event that now
include the normalized input, the active `rules_version`, and the top three
match-kind buckets via stable keys (`match_top_{n}_kind` /
`match_top_{n}_count`). This allows dashboards to trend the distribution of
match outcomes without re-parsing ad-hoc JSON payloads.

Alias updates continue to log `alias_update` events. When an added or removed
alias exactly equals the canonical normalized PN, the payload includes a
`rule_ids` map keyed by bucket (`added` / `removed`) listing the normalization
rules associated with that canonical form. No other aliases emit rule ids to
keep logs concise.
