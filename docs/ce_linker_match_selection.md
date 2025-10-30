## Purpose

These directives specify the end-to-end behavior of the part-number (PN) → Complex candidate
matching subsystem. Given any raw PN string, the system must deterministically surface the most
relevant Complex entries from CE Bridge, explain why each result appeared, and decide whether the
match can be auto-attached or must be escalated to an operator.

The design fuses the existing CE Bridge workflow—match kinds, normalization, ranking,
`trace_id`, and review gating—with the functional PN parsing research that understands how
electronic component numbers encode packages, grades, and multi-vendor families.

The implementation lives inside the `ce_linker_match_selection` module and is consumed by both the
background auto-linker and the Complex Panel UI.

---

## 1. System contract

**Input**: An arbitrary PN string originating from a BOM import, manual entry, or operator input.
The string may contain packaging codes, RoHS markers, tape-and-reel suffixes, temperature grades,
etc.

**Output**: A structured decision payload containing a ranked list of Complex candidates grouped by
closeness, metadata describing why each row was suggested, and an explicit review decision.

**Safety**: The subsystem must never silently attach an incorrect Complex. Ambiguous or degraded
matches force operator review and preserve every candidate for manual override. CE Bridge remains the
source of truth for canonical Complex records; BOM_DB never fabricates matches locally.

**Observability**: Every query owns a deterministic `trace_id`. The identifier is logged locally,
forwarded to CE Bridge via `X-Trace-Id`, and included in the final decision payload so support teams
can replay behavior later.

---

## 2. Processing pipeline

All requests pass through the following ordered stages:

### 2.1 Validate input

Reject empty strings, wildcard-only tokens, and other malformed input immediately by raising
`LinkerInputError`. Validation failures terminate the request before contacting CE Bridge.

### 2.2 Generate `trace_id`

Create a new 32-character hexadecimal identifier and attach it to every log entry, outbound HTTP
header, and the final decision object.

### 2.3 Derive PN search keys

Produce an ordered list of unique search keys:

1. **Direct key** – the raw PN string. This preserves fidelity for exact and alias matches.
2. **Core keys** – deterministic derivatives produced by structurally stripping non-functional
   suffixes and recognized vendor prefixes. Core extraction is defined in §3.

### 2.4 Query CE Bridge

1. Call `GET /state` and assert:
   * `features.search_match_kind == true`
   * `features.normalization_rules_version == "v1"`
   Failure raises `LinkerFeatureError`.
2. For each unique key, call `GET /complexes/search` with parameters `pn=<key>`, `limit=<N>` (from
   configuration), and `analyze=true`.

Every request includes the authorization token (when configured) and `X-Trace-Id: <trace_id>`.
Responses from all keys are merged and de-duplicated by CE ID.

### 2.5 Rank and classify candidates

For each returned row, capture the CE metadata (ID, canonical PN, aliases, `match_kind`, CE reason,
normalization fields) and annotate the local match tier defined in §4.

Primary sort order is fixed to CE Bridge `match_kind` priority:

1. `exact_pn`
2. `exact_alias`
3. `normalized_pn`
4. `normalized_alias`
5. `like`

Tiers apply as a secondary grouping layer without disturbing the per-kind ordering.

### 2.6 Produce decision object

Assemble a `LinkerDecision` dataclass instance containing:

* `query`: original PN string.
* `trace_id`: generated identifier.
* `results`: the full ranked candidate list (never filtered).
* `best`: the unique top-ranked candidate, if unambiguous.
* `needs_review`: boolean computed via §5.
* `rationale`: human-readable explanation for the review decision.

The decision is returned to both the background auto-link workflow and the operator-facing UI.

---

## 3. Core key extraction logic

Core keys express the functional identity of a PN while discarding shipping-only noise. Extraction is
deterministic and rule-driven; when rules do not apply, the system keeps the PN unchanged rather than
guessing.

### 3.1 Remove non-functional suffixes

Strip trailing patterns known to represent tape-and-reel indicators, reel lengths, or environmental
markers (e.g., `TR`, `RL`, `REEL`, `LF`, `G4`, `+`). Removing these suffixes prevents superficial
packaging differences from blocking a match.

### 3.2 Handle removable manufacturer prefixes

Maintain a lookup table of vendor prefixes that are safe to drop for particular numeric families
(e.g., `SN`/`M`/`74` logic series, `LM`/`MC`/`KA` regulators, `MAX`/`ICL`/`ST` interface chips).
When a PN begins with a recognized removable prefix for the detected family, create an additional
core variant without the prefix. Unrecognized prefixes remain untouched.

### 3.3 Separate package / temperature / grade clusters

Identify known tail codes that encode only mechanical package, temperature range, or shipment method
(e.g., `N`, `D`, `PW`, `C`, `I`). Peel those codes off to generate the primary core. Grade letters
that alter electrical performance (e.g., `TL074A` vs `TL074`) are preserved to avoid collapsing
distinct silicon bins.

### 3.4 Core variants

* **primary_core** – PN with removable shipping and package codes removed while retaining any grade
  information.
* **family_core** – optional broader code representing cross-manufacturer families (e.g., removing
  `SN` from `SN74HC595` or `MC` from `MC7805`).

When multiple confident extractions apply, add each resulting key to the search list after the direct
PN. Ambiguous patterns are skipped.

---

## 4. Post-search interpretation and match tiers

Match tiers enrich CE Bridge results with functional meaning and drive review behavior.

### Tier 0 – Exact silicon identity

* CE `match_kind`: `exact_pn` or `exact_alias`.
* Candidate was discovered using the direct key.
* Represents the same CE canonical PN or alias.
* Eligible for auto-attachment only when it is the unique top-ranked candidate and §5 review rules
  permit.

### Tier 1 – Same silicon, ordering variant

* CE `match_kind`: `normalized_pn` or `normalized_alias`.
* Matches the `primary_core` (package / reel / temp variants).
* Displayed as “same silicon, different package or grade”.
* Always requires operator confirmation; never auto-link solely on Tier 1.

### Tier 2 – Cross-manufacturer equivalent

* CE `match_kind`: any value (`exact_*`, `normalized_*`, `like`).
* Matches the `family_core` or a whitelisted second-source mapping (e.g., `LM7805` ↔ `MC7805`).
* Surface with messaging such as “Cross-manufacturer equivalent; verify pinout/grade”.
* Always sets `needs_review = True`.

### Tier 3 – Loose similarity

* CE `match_kind`: `like` only.
* Appears exclusively when searching core-derived keys.
* Serves as a “for investigation” suggestion and is sorted last.
* Always sets `needs_review = True`.

Candidates are grouped by tier after sorting by `match_kind` to provide operators with a clear
confidence ladder.

---

## 5. Decision and review policy

`needs_review` is computed using the following rules:

1. No candidates → `best = None`, `needs_review = True`.
2. Multiple candidates share the highest `match_kind` priority → `needs_review = True`.
3. `best.match_kind` is not `exact_pn`/`exact_alias` → `needs_review = True`.
4. `best` is Tier 2 or Tier 3 → `needs_review = True`.
5. Otherwise (`best` is a unique Tier 0 match) → `needs_review = False`.

Auto-linking in the background import path proceeds only when `best` exists, `needs_review` is
`False`, and the top candidate is a Tier 0 `exact_pn`/`exact_alias`. All other scenarios preserve the
full result list for operator action.

Each decision stores a textual `rationale` explaining why auto-linking was or was not permitted, to
improve UI clarity and post-incident analysis.

---

## 6. Operator-facing UI expectations

The Complex Panel (Qt UI) must display:

* Complete candidate table with canonical PN, CE ID, aliases, `match_kind`, tier, CE reason,
  normalization data, and parsed core notes (e.g., “same silicon – DIP vs SOIC”).
* Prominent display of the system-selected best candidate, the `needs_review` flag, the `trace_id`,
  and the CE Bridge shard / database path.
* Controls allowing operators to attach any candidate, overriding the best row when necessary. The
  override action logs the `trace_id` with the chosen CE ID.
* Clear error surfaces for authentication, network, or feature mismatches. On failure the UI clears
  stale results and invites retry.

When present, core-derived suggestions must annotate which key produced the candidate (direct, primary
core, or family core) so operators understand the derivation path.

---

## 7. Logging and auditability

For every query the subsystem logs:

* `trace_id`
* Original PN
* All generated search keys (direct, primary, family)
* Full CE Bridge responses per key
* Ranked candidate list with tiers, `needs_review`, and `rationale`
* Final action (`auto-attached`, `operator-attached`, or `no attachment`)

Logs allow CE Support and BOM_DB Support to replay behavior through CE Bridge’s
`/admin/logs/{trace_id}` endpoint.

---

## 8. Hard requirements snapshot

* CE Bridge remains authoritative for canonical matches and normalization.
* PN parsing must deterministically generate core search keys; no guesswork.
* All keys query CE Bridge with `analyze=true` and share a `trace_id`.
* Ranking first respects CE `match_kind`, then applies tiers.
* Auto-link is allowed only for a unique Tier 0 `exact_pn`/`exact_alias`.
* The operator UI always shows every candidate with clear tiering and rationale.
* The system fails safe—errors prevent auto-attachment and surface diagnostics to operators.

---

## 9. Operational summary

Following these directives ensures we preserve CE Bridge contracts, improve match quality via PN
structure awareness, and retain full auditability. Operators receive explicit context for exact
matches, same-silicon ordering variants, second-source equivalents, and loose suggestions without the
system ever silently guessing.
