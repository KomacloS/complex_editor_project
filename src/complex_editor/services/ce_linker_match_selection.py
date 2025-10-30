"""Deterministic CE Bridge match selection logic.

This module implements the requirements captured in
``docs/ce_linker_match_selection.md``.  The entry point is
``run_match_selection`` which orchestrates validation, core key derivation,
CE Bridge queries, ranking, tiering, and final decision building.

The implementation is intentionally verbose so that the surrounding tooling
and operator UI can inspect the intermediate data structures and surface
clear audit logs for each PN query.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
import json
import logging
import re
import secrets
from typing import Iterable, List, Mapping, MutableMapping, Optional, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ce_bridge_service.models import MatchKind

logger = logging.getLogger(__name__)


class LinkerInputError(ValueError):
    """Raised when the incoming PN is empty or obviously invalid."""


class LinkerFeatureError(RuntimeError):
    """Raised when CE Bridge does not expose the required match features."""


class LinkerBridgeError(RuntimeError):
    """Raised when HTTP communication with CE Bridge fails."""


class BridgeClient(Protocol):
    """Minimal client interface used by the linker logic."""

    def fetch_state(self, *, trace_id: str) -> Mapping[str, object]:
        """Return the payload from ``GET /state``."""

    def search(
        self,
        pn: str,
        *,
        limit: int,
        analyze: bool,
        trace_id: str,
    ) -> Iterable[Mapping[str, object]]:
        """Return the search payload for ``GET /complexes/search``."""


class HttpBridgeClient:
    """Very small ``urllib`` based CE Bridge client."""

    def __init__(self, base_url: str, *, auth_token: str | None = None, timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/") or "http://127.0.0.1:8765"
        self._auth_token = auth_token
        self._timeout = float(timeout)

    def _request(self, path: str, *, trace_id: str, params: Mapping[str, object] | None = None) -> Mapping[str, object]:
        url = f"{self._base_url}{path}"
        if params:
            query = urlencode(params)
            url = f"{url}?{query}"
        headers = {"User-Agent": "ce-linker/1.0", "X-Trace-Id": trace_id}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=self._timeout) as resp:
                payload = resp.read()
        except (URLError, HTTPError) as exc:  # pragma: no cover - exercised in integration
            raise LinkerBridgeError(str(exc)) from exc
        data = json.loads(payload)
        if not isinstance(data, Mapping):
            raise LinkerBridgeError("Unexpected response structure")
        return data

    def fetch_state(self, *, trace_id: str) -> Mapping[str, object]:
        return self._request("/state", trace_id=trace_id)

    def search(
        self,
        pn: str,
        *,
        limit: int,
        analyze: bool,
        trace_id: str,
    ) -> Iterable[Mapping[str, object]]:
        params = {"pn": pn, "limit": int(limit)}
        if analyze:
            params["analyze"] = "true"
        data = self._request("/complexes/search", trace_id=trace_id, params=params)
        results = data if isinstance(data, list) else data.get("results", [])
        if not isinstance(results, list):
            raise LinkerBridgeError("Unexpected search response structure")
        return [row for row in results if isinstance(row, Mapping)]


MATCH_KIND_PRIORITY: Mapping[MatchKind | None, int] = {
    MatchKind.EXACT_PN: 0,
    MatchKind.EXACT_ALIAS: 1,
    MatchKind.NORMALIZED_PN: 2,
    MatchKind.NORMALIZED_ALIAS: 3,
    MatchKind.LIKE: 4,
    None: 99,
}


class MatchTier(IntEnum):
    """Match tier encodes the local interpretation of CE Bridge results."""

    TIER_0 = 0
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3


@dataclass(slots=True)
class MatchCandidate:
    ce_id: int
    canonical_pn: str
    aliases: List[str]
    match_kind: MatchKind | None
    reason: str | None
    normalized_input: str | None
    normalized_targets: List[str]
    tier: MatchTier
    via: str
    rule_ids: List[str]
    sources: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Mapping[str, object]:
        return {
            "ce_id": self.ce_id,
            "canonical_pn": self.canonical_pn,
            "aliases": list(self.aliases),
            "match_kind": None if self.match_kind is None else self.match_kind.value,
            "reason": self.reason,
            "normalized_input": self.normalized_input,
            "normalized_targets": list(self.normalized_targets),
            "tier": int(self.tier),
            "via": self.via,
            "rule_ids": list(self.rule_ids),
            "sources": list(self.sources),
        }


@dataclass(slots=True)
class MatchDecision:
    query: str
    trace_id: str
    results: List[MatchCandidate]
    best: Optional[MatchCandidate]
    needs_review: bool
    rationale: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "query": self.query,
            "trace_id": self.trace_id,
            "results": [cand.to_dict() for cand in self.results],
            "best": None if self.best is None else self.best.to_dict(),
            "needs_review": bool(self.needs_review),
            "rationale": self.rationale,
        }


@dataclass(slots=True)
class _CandidateAccumulator:
    ce_id: int
    canonical_pn: str
    aliases: List[str]
    sources: set[str]
    best_key_type: str
    best_priority: int
    best_match_kind: MatchKind | None
    best_reason: str | None
    best_normalized_input: str | None
    best_normalized_targets: List[str]
    best_rule_ids: List[str]
    first_seen_order: int

    def update_best(
        self,
        *,
        key_type: str,
        priority: int,
        match_kind: MatchKind | None,
        reason: str | None,
        normalized_input: str | None,
        normalized_targets: List[str],
        rule_ids: List[str],
    ) -> None:
        self.best_key_type = key_type
        self.best_priority = priority
        self.best_match_kind = match_kind
        self.best_reason = reason
        self.best_normalized_input = normalized_input
        self.best_normalized_targets = normalized_targets
        self.best_rule_ids = rule_ids


def run_match_selection(
    pn: str,
    *,
    client: BridgeClient,
    limit: int = 20,
    logger_: logging.Logger | None = None,
) -> MatchDecision:
    """Execute the deterministic match selection pipeline."""

    logger_local = logger_ or logger
    cleaned = pn.strip()
    if not cleaned or not any(ch.isalnum() for ch in cleaned):
        raise LinkerInputError("pn must not be empty")

    trace_id = secrets.token_hex(16)
    logger_local.info("linker.start", extra={"trace_id": trace_id, "query": cleaned})

    state = client.fetch_state(trace_id=trace_id)
    _assert_features(state)

    keys = _derive_search_keys(cleaned)
    logger_local.debug("linker.keys", extra={"trace_id": trace_id, "keys": keys})

    aggregated: MutableMapping[int, _CandidateAccumulator] = {}
    order_counter = 0

    for key_index, (key_type, key_value) in enumerate(keys):
        results = list(client.search(key_value, limit=limit, analyze=True, trace_id=trace_id))
        logger_local.debug(
            "linker.bridge_response",
            extra={
                "trace_id": trace_id,
                "key_type": key_type,
                "key": key_value,
                "count": len(results),
            },
        )
        logger_local.debug(
            "linker.bridge_results",
            extra={
                "trace_id": trace_id,
                "key_type": key_type,
                "key": key_value,
                "results": results,
            },
        )
        for result_index, row in enumerate(results):
            try:
                ce_id = int(row["id"])
            except Exception:
                continue
            canonical = str(row.get("pn", "")).strip() or cleaned
            aliases = [str(alias) for alias in row.get("aliases", []) if isinstance(alias, str)]
            match_kind_raw = row.get("match_kind")
            match_kind = MatchKind(match_kind_raw) if match_kind_raw in MatchKind._value2member_map_ else None
            priority = MATCH_KIND_PRIORITY.get(match_kind, 99)
            reason = row.get("reason") if isinstance(row.get("reason"), str) else None
            normalized_input = row.get("normalized_input")
            if normalized_input is not None:
                normalized_input = str(normalized_input)
            normalized_targets = [
                str(val)
                for val in row.get("normalized_targets", [])
                if isinstance(val, str)
            ]
            rule_ids = [str(val) for val in row.get("rule_ids", []) if isinstance(val, str)]

            entry = aggregated.get(ce_id)
            if entry is None:
                entry = _CandidateAccumulator(
                    ce_id=ce_id,
                    canonical_pn=canonical,
                    aliases=aliases,
                    sources={key_type},
                    best_key_type=key_type,
                    best_priority=priority,
                    best_match_kind=match_kind,
                    best_reason=reason,
                    best_normalized_input=normalized_input,
                    best_normalized_targets=normalized_targets,
                    best_rule_ids=rule_ids,
                    first_seen_order=order_counter,
                )
                aggregated[ce_id] = entry
                order_counter += 1
            else:
                entry.sources.add(key_type)
                better_priority = priority < entry.best_priority
                same_priority_prefer_direct = (
                    priority == entry.best_priority
                    and entry.best_key_type != "direct"
                    and key_type == "direct"
                )
                if better_priority or same_priority_prefer_direct:
                    entry.update_best(
                        key_type=key_type,
                        priority=priority,
                        match_kind=match_kind,
                        reason=reason,
                        normalized_input=normalized_input,
                        normalized_targets=normalized_targets,
                        rule_ids=rule_ids,
                    )

    candidates = [
        _build_candidate(acc)
        for acc in aggregated.values()
    ]

    candidates.sort(
        key=lambda cand: (
            MATCH_KIND_PRIORITY.get(cand.match_kind, 99),
            int(cand.tier),
            _first_seen_for(aggregated, cand.ce_id),
        )
    )

    logger_local.debug(
        "linker.candidates",
        extra={
            "trace_id": trace_id,
            "candidates": [cand.to_dict() for cand in candidates],
        },
    )

    best = candidates[0] if candidates else None
    needs_review, rationale = _compute_review_state(best, candidates)

    decision = MatchDecision(
        query=cleaned,
        trace_id=trace_id,
        results=candidates,
        best=best,
        needs_review=needs_review,
        rationale=rationale,
    )

    logger_local.info(
        "linker.decision",
        extra={
            "trace_id": trace_id,
            "needs_review": needs_review,
            "best": None if best is None else best.to_dict(),
            "candidate_count": len(candidates),
        },
    )

    return decision


def _assert_features(state: Mapping[str, object]) -> None:
    if not isinstance(state, Mapping):
        raise LinkerFeatureError("bridge state response malformed")
    features = state.get("features")
    if not isinstance(features, Mapping):
        raise LinkerFeatureError("bridge state missing features block")
    if not bool(features.get("search_match_kind")):
        raise LinkerFeatureError("search_match_kind feature disabled")
    version = features.get("normalization_rules_version")
    if version != "v1":
        raise LinkerFeatureError("unexpected normalization rules version")


NON_FUNCTIONAL_SUFFIXES = (
    "TR",
    "T",
    "R",
    "RL",
    "REEL",
    "R2",
    "R3",
    "R4",
    "R5",
    "R7",
    "R8",
    "T7",
    "T13",
    "T5",
)

COMPLIANCE_SUFFIXES = (
    "G",
    "G4",
    "E4",
    "LF",
    "LFT",
    "PBF",
    "PB",
)

PACKAGE_SUFFIXES = {
    "N",
    "D",
    "DR",
    "DW",
    "PW",
    "PWR",
    "PS",
    "PE",
    "DGK",
    "DGKR",
    "DB",
    "DBR",
    "DT",
    "DBV",
    "SO",
    "SOIC",
    "SOIC8",
    "SOIC14",
    "SOP",
    "SSOP",
    "MSOP",
    "TSSOP",
    "PDIP",
    "QFN",
    "QFP",
    "LQFP",
    "TO220",
    "TO247",
}

GRADE_CODES = {"A", "B"}

_TOKEN_SPLIT_RE = re.compile(r"[\s\-_.+/]+")


def _derive_search_keys(pn: str) -> List[tuple[str, str]]:
    normalized = pn.strip()
    tokens = _tokenize(normalized)
    primary_core = _build_primary_core(tokens)
    family_core = _build_family_core(primary_core)

    keys: List[tuple[str, str]] = [("direct", normalized)]
    if primary_core and primary_core != normalized:
        keys.append(("primary_core", primary_core))
    if family_core and family_core not in {normalized, primary_core}:
        keys.append(("family_core", family_core))
    return keys


def _tokenize(pn: str) -> List[str]:
    stripped = _TOKEN_SPLIT_RE.sub("", pn.upper())
    if not stripped:
        return []
    tokens: List[str] = []
    current = stripped[0]
    for ch in stripped[1:]:
        if ch.isalpha() == current[-1].isalpha():
            current += ch
        else:
            tokens.append(current)
            current = ch
    tokens.append(current)
    combined: List[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"R", "T"} and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            digits = tokens[i + 1]
            j = i + 2
            while j < len(tokens) and tokens[j].isdigit():
                digits += tokens[j]
                j += 1
            combined.append(token + digits)
            i = j
            continue
        if token in {"G", "E"} and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            combined.append(token + tokens[i + 1])
            i += 2
            continue
        if token in {"SO", "SOIC", "SOP", "SSOP", "TSSOP", "MSOP", "QFN", "QFP", "LQFP", "TO"} and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            combined.append(token + tokens[i + 1])
            i += 2
            continue
        combined.append(token)
        i += 1
    return combined


def _build_primary_core(tokens: List[str]) -> str:
    if not tokens:
        return ""
    working = list(tokens)

    while working and _matches_suffix(working[-1], NON_FUNCTIONAL_SUFFIXES):
        working.pop()

    while working and _matches_suffix(working[-1], COMPLIANCE_SUFFIXES):
        working.pop()

    while len(working) >= 2 and working[-1].isdigit() and working[-2].endswith(("R", "T")):
        working.pop()
        trimmed = working.pop()
        trimmed = trimmed[:-1]
        if trimmed:
            working.append(trimmed)

    while working:
        tail = working[-1]
        if tail in GRADE_CODES:
            break
        if _is_package_token(tail):
            working.pop()
            continue
        break

    return "".join(working)


def _build_family_core(primary_core: str) -> str:
    if not primary_core:
        return ""
    for prefixes, pattern in _FAMILY_PREFIX_RULES:
        for prefix in prefixes:
            if primary_core.startswith(prefix):
                remainder = primary_core[len(prefix) :]
                if remainder and pattern.match(remainder):
                    return remainder
    return ""


_FAMILY_PREFIX_RULES: List[tuple[tuple[str, ...], re.Pattern[str]]] = [
    (("SN", "M"), re.compile(r"^74[A-Z0-9].*$")),
    (("MC", "KA", "LM"), re.compile(r"^(78|79)[0-9].*$")),
    (("MAX", "ICL", "ST", "ADM"), re.compile(r"^232[A-Z0-9]*$")),
]


def _matches_suffix(token: str, suffixes: Iterable[str]) -> bool:
    return any(token == suffix for suffix in suffixes)


def _is_package_token(token: str) -> bool:
    if token in PACKAGE_SUFFIXES:
        return True
    if token.startswith("SOIC") or token.startswith("SO") and token.endswith("W"):
        return True
    if token.startswith("TO") and len(token) <= 5:
        return True
    return False


def _build_candidate(entry: _CandidateAccumulator) -> MatchCandidate:
    tier = _classify_tier(entry.best_key_type, entry.best_match_kind)
    via = _describe_via(entry.best_key_type, tier)
    return MatchCandidate(
        ce_id=entry.ce_id,
        canonical_pn=entry.canonical_pn,
        aliases=entry.aliases,
        match_kind=entry.best_match_kind,
        reason=entry.best_reason,
        normalized_input=entry.best_normalized_input,
        normalized_targets=entry.best_normalized_targets,
        tier=tier,
        via=via,
        rule_ids=entry.best_rule_ids,
        sources=tuple(sorted(entry.sources)),
    )


def _classify_tier(key_type: str, match_kind: MatchKind | None) -> MatchTier:
    if key_type == "direct":
        if match_kind in {MatchKind.EXACT_PN, MatchKind.EXACT_ALIAS}:
            return MatchTier.TIER_0
        if match_kind in {MatchKind.NORMALIZED_PN, MatchKind.NORMALIZED_ALIAS}:
            return MatchTier.TIER_1
        return MatchTier.TIER_3
    if key_type == "primary_core":
        if match_kind in {MatchKind.EXACT_PN, MatchKind.EXACT_ALIAS, MatchKind.NORMALIZED_PN, MatchKind.NORMALIZED_ALIAS}:
            return MatchTier.TIER_1
        return MatchTier.TIER_3
    if key_type == "family_core":
        if match_kind == MatchKind.LIKE:
            return MatchTier.TIER_3
        return MatchTier.TIER_2
    return MatchTier.TIER_3


def _describe_via(key_type: str, tier: MatchTier) -> str:
    if tier == MatchTier.TIER_0:
        return "exact match on direct key"
    if tier == MatchTier.TIER_1:
        return "same silicon via primary core"
    if tier == MatchTier.TIER_2:
        return "cross-family equivalent via family core"
    return "suggested via derived LIKE search"


def _first_seen_for(aggregated: Mapping[int, _CandidateAccumulator], ce_id: int) -> int:
    entry = aggregated.get(ce_id)
    return entry.first_seen_order if entry else 0


def _compute_review_state(
    best: Optional[MatchCandidate],
    candidates: List[MatchCandidate],
) -> tuple[bool, str]:
    if not candidates:
        return True, "No candidates found; operator review required."
    if best is None:
        return True, "No candidates found; operator review required."

    best_priority = MATCH_KIND_PRIORITY.get(best.match_kind, 99)
    same_priority = sum(1 for cand in candidates if MATCH_KIND_PRIORITY.get(cand.match_kind, 99) == best_priority)
    if same_priority > 1:
        return True, "Multiple candidates share the top match kind; operator review required."

    if best.match_kind not in {MatchKind.EXACT_PN, MatchKind.EXACT_ALIAS}:
        return True, "Top candidate is not an exact match; operator must confirm."

    if int(best.tier) >= MatchTier.TIER_2:
        return True, "Cross-family or loose match requires review."

    return False, "Unique exact match eligible for automatic attachment."


__all__ = [
    "BridgeClient",
    "HttpBridgeClient",
    "LinkerBridgeError",
    "LinkerFeatureError",
    "LinkerInputError",
    "MatchCandidate",
    "MatchDecision",
    "MatchTier",
    "run_match_selection",
]

