## Overview

Complex Editor (CE) Bridge is the authoritative service for part search, alias resolution, and normalization. Given an arbitrary Bill of Materials (BOM) part number string (PN), our goal is to identify the correct Complex entry in CE. BOM_DB never guesses locally; every decision originates from CE Bridge responses.

## Request flow

BOM_DB issues lookups by calling `ce_bridge_linker.select_best_match(pn, limit=N)`. The helper performs the following steps:

1. Validate the PN. Empty strings, wildcard-only tokens, and other invalid values raise `LinkerInputError` before contacting CE Bridge.
2. Generate a new 32-character hexadecimal `trace_id` and include it in all downstream logging.
3. Call `GET /state` on CE Bridge, requiring:
   * `features.search_match_kind == true`
   * `features.normalization_rules_version == "v1"`
4. Call `GET /complexes/search?pn=<value>&limit=<N>&analyze=true` to retrieve ranked candidates.

Headers forwarded on both HTTP requests:

* `Authorization: Bearer <token>` when BOM_DB is configured with a CE API token.
* `X-Trace-Id: <32-hex>` to correlate requests across BOM_DB and CE Bridge logs. This enables deterministic reproduction, escalations to support, and post-mortem analysis.

## CE Bridge response shape

`/complexes/search` returns an array of result objects. Each object may contain:

* `id` / `ce_id` / `comp_id`: the Complex identifier inside CE.
* `pn`: canonical CE part number.
* `aliases`: list of known aliases for the Complex.
* `match_kind`: textual reason for the match. Current values are `exact_pn`, `exact_alias`, `normalized_pn`, `normalized_alias`, and `like`.
* `reason`: short human-readable justification.
* `normalized_input`: normalized representation of the query PN computed by CE Bridge.
* `normalized_targets`: normalized representations of the candidate PN and aliases.
* `analysis.normalized_input` / `analysis.normalized_targets`: future-compatible duplication of normalization data.
* `db_path` / `ce_db_uri`: CE database shard containing the Complex (displayed for operators).

CE Bridge owns normalization rules. BOM_DB can inspect them via `GET /admin/pn_normalization`, surfaced to operators through **Settings ▸ “Normalization Rules…”**. That UI calls `fetch_normalization_info()` which wraps both `/admin/pn_normalization` and `/state`.

### Example request

```json
{
  "method": "GET",
  "url": "/complexes/search",
  "params": {
    "pn": "abc-123 rev.A",
    "limit": 10,
    "analyze": true
  },
  "headers": {
    "Authorization": "Bearer <token>",
    "X-Trace-Id": "5f1c2a7b8d9048b7bfbf3a19c3f1a0de"
  }
}
```

### Example response excerpt

```json
[
  {
    "id": "ce-001",
    "pn": "ABC-123",
    "aliases": ["abc123", "ABC-123-REV-A"],
    "match_kind": "normalized_pn",
    "reason": "Input normalized to PN variant",
    "normalized_input": "abc123",
    "normalized_targets": ["abc123", "abc123reva"],
    "analysis": {
      "normalized_input": "abc123",
      "normalized_targets": ["abc123", "abc123reva"]
    },
    "db_path": "prod/main"
  },
  {
    "id": "ce-219",
    "pn": "ABC-123-ALT",
    "aliases": ["abc-123-alt"],
    "match_kind": "like",
    "reason": "Loose LIKE comparison",
    "normalized_input": "abc123",
    "normalized_targets": ["abc123alt"],
    "db_path": "prod/archive"
  }
]
```

## Ranking and selection

`select_best_match()` ranks candidates using the CE Bridge-provided `match_kind`. Priority order from highest to lowest:

1. `exact_pn`
2. `exact_alias`
3. `normalized_pn`
4. `normalized_alias`
5. `like`

The helper walks the result list, maps each `match_kind` to that priority, and chooses the highest-ranked row as `decision.best`. If multiple rows share the top rank, `decision.needs_review` becomes `True`; otherwise it is `False`.

```python
@dataclass
class LinkCandidate:
    id: str
    pn: str
    aliases: list[str]
    match_kind: str
    reason: str
    normalized_input: Optional[str]
    normalized_targets: list[str]
    raw: dict

@dataclass
class LinkerDecision:
    query: str
    trace_id: str
    results: list[dict]
    best: Optional[LinkCandidate]
    needs_review: bool
```

`trace_id` propagates to CE Bridge via the `X-Trace-Id` header and appears in CE logs, enabling cross-system debugging.

## BOM_DB behaviors

### 5.1 Background auto-link (no UI)

Implementation: `app/domain/complex_linker.py::auto_link_by_pn(...)`.

Process:

1. Invoke `select_best_match(pn, limit=10)`.
2. If `decision.best` is `None`, stop.
3. If `decision.needs_review` is `True`, stop because the match is ambiguous.
4. If `decision.best.match_kind` is neither `exact_pn` nor `exact_alias`, stop.
5. Otherwise call `attach_existing_complex(part_id, decision.best.id)`, log `decision.trace_id`, and return `True`.

This is the sole pathway where BOM_DB silently attaches a Complex without operator input.

### 5.2 Complex Panel (interactive UI)

Implementation: `app/gui/widgets/complex_panel.py::_on_search_clicked`.

Steps:

1. Call `select_best_match(query, limit=50)`.
2. Populate the UI list widget with every row from `decision.results` (never filtered).
3. Each list entry shows PN, CE ID, aliases, DB path, match kind, reason, and truncated normalization data.
4. Highlight `decision.best` so the operator sees the preferred candidate.
5. Display a status line: `Found N result(s) | Trace: <trace_id> | Best: <pn/id> [<match_kind>] | needs review: <bool>`.
6. When the user clicks **Attach**, we take the currently selected row (which may differ from `decision.best`) and call `attach_existing_complex(...)`.

Operators can always override the ranked best candidate. The panel presents the entire CE candidate list, not just the top entry.

## Error handling and safety

Exceptions raised by `select_best_match()`:

* `LinkerInputError`: invalid PN before contacting CE Bridge.
* `LinkerFeatureError`: CE Bridge lacks `search_match_kind` or the normalization rules are not version `v1`.
* `LinkerNetworkError`: network or transport failure reaching CE Bridge.
* `LinkerAuthError`: authentication or authorization failure.
* `LinkerError`: generic fallback for other unexpected conditions.

GUI responses:

* Show a `QMessageBox` labelled “Authentication”, “Network”, or “Search failed” depending on the exception class.
* Clear the result list on failure.
* Update `status_label` with `decision.trace_id` when a search succeeds.

Auto-link responses:

* Catch `LinkerError` (including subclasses) and return `False` so imports never crash when CE is unavailable.

## Operational notes

* Every request includes `X-Trace-Id`. CE support retrieves correlated logs through `GET /admin/logs/{trace_id}`.
* Normalization rules may change between CE Bridge deployments. Operators can inspect current rules via Settings ▸ “Normalization Rules…”, which executes `fetch_normalization_info()` and surfaces `/admin/pn_normalization` plus `/state` data.
* When `decision.needs_review == True`, auto-linking is suppressed to keep an operator in the loop.

## TL;DR for support / onboarding

* CE Bridge is the authority: it returns all potential Complex matches.
* BOM_DB queries CE Bridge once per PN and stamps each call with a trace id.
* Matches are ranked by `match_kind`.
* Only a unique `exact_pn` or `exact_alias` result triggers automatic attachment.
* The Complex panel always shows every CE candidate and lets an operator choose.
* Trace ids enable CE and BOM_DB teams to debug mismatches after the fact.
