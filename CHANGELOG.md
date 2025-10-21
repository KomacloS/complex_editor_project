## Unreleased

- Rename main application window to "Complex View".
- Add new "Complex Editor" dialog for creating and editing complexes.
- Share pin validation helpers across UIs and support parameter editing.
- Docs: Added CE_BRIDGE_API.md.
- Logging: centralized configuration, default WARNING, debug markers demoted, logs to file via env.
- Bridge: `/complexes/search` now supports `analyze=true` to return match_kind, normalization
  details, and rule identifiers for BOM_DB linking. Exact matches are
  case-insensitive, normalized matches require a non-empty normalized input, and
  wildcard-only queries are rejected with HTTP 400.
- Bridge: `/state` advertises headless and `allow_headless` flags and reports
  `features.export_mdb` as true only when exports are currently permitted.
- Bridge: Added `GET /admin/pn_normalization` for support diagnostics, widened
  default normalization punctuation removal, and exposed normalization telemetry
  (rules version plus top match-kind buckets) in search logs. Alias update logs
  include rule identifiers only when aliases mirror the canonical normalized PN.
- BREAKING: none.
- Docs aligned with `/state.features` bridge snapshot.
