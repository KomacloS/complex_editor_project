from __future__ import annotations

from dataclasses import dataclass

import pytest

from complex_editor.services.ce_linker_match_selection import (
    BridgeClient,
    LinkerFeatureError,
    LinkerInputError,
    MatchTier,
    run_match_selection,
)


@dataclass
class FakeBridge(BridgeClient):
    state_payload: dict[str, object]
    responses: dict[str, list[dict[str, object]]]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def fetch_state(self, *, trace_id: str) -> dict[str, object]:  # type: ignore[override]
        self.calls.append(("state", trace_id))
        return self.state_payload

    def search(self, pn: str, *, limit: int, analyze: bool, trace_id: str):  # type: ignore[override]
        self.calls.append((pn, trace_id))
        return list(self.responses.get(pn, []))


def test_unique_exact_match_allows_auto_link():
    bridge = FakeBridge(
        state_payload={
            "features": {"search_match_kind": True, "normalization_rules_version": "v1"}
        },
        responses={
            "LM358DR2G": [
                {
                    "id": 1,
                    "pn": "LM358DR2G",
                    "aliases": ["LM358DR2G"],
                    "match_kind": "exact_pn",
                    "reason": "Exact PN match",
                    "normalized_input": "LM358DR2G",
                    "normalized_targets": ["LM358DR2G"],
                }
            ],
            "LM358": [
                {
                    "id": 1,
                    "pn": "LM358D",
                    "aliases": ["LM358DR2G"],
                    "match_kind": "normalized_pn",
                    "reason": "Normalized match",
                    "normalized_input": "LM358",
                    "normalized_targets": ["LM358"],
                }
            ],
        },
    )

    decision = run_match_selection(" LM358DR2G ", client=bridge)

    assert decision.query == "LM358DR2G"
    assert len(decision.trace_id) == 32
    assert decision.best is not None
    assert decision.best.ce_id == 1
    assert decision.best.tier == MatchTier.TIER_0
    assert decision.needs_review is False
    assert "automatic" in decision.rationale.lower()
    assert [call[0] for call in bridge.calls if call[0] != "state"] == ["LM358DR2G", "LM358"]


def test_multiple_exact_matches_force_review():
    bridge = FakeBridge(
        state_payload={
            "features": {"search_match_kind": True, "normalization_rules_version": "v1"}
        },
        responses={
            "SN74HC595N": [
                {
                    "id": 10,
                    "pn": "SN74HC595N",
                    "aliases": [],
                    "match_kind": "exact_pn",
                    "reason": "Exact",
                },
                {
                    "id": 11,
                    "pn": "SN74HC595DR",
                    "aliases": ["SN74HC595N"],
                    "match_kind": "exact_pn",
                    "reason": "Exact",
                },
            ]
        },
    )

    decision = run_match_selection("SN74HC595N", client=bridge)

    assert decision.needs_review is True
    assert "multiple" in decision.rationale.lower()


def test_primary_and_family_core_tiering():
    bridge = FakeBridge(
        state_payload={
            "features": {"search_match_kind": True, "normalization_rules_version": "v1"}
        },
        responses={
            "SN74HC595N": [],
            "SN74HC595": [
                {
                    "id": 20,
                    "pn": "SN74HC595DR",
                    "aliases": [],
                    "match_kind": "normalized_pn",
                    "reason": "Package variant",
                }
            ],
            "74HC595": [
                {
                    "id": 21,
                    "pn": "M74HC595B1R",
                    "aliases": [],
                    "match_kind": "normalized_alias",
                    "reason": "Cross manufacturer",
                },
                {
                    "id": 22,
                    "pn": "74HC596",
                    "aliases": [],
                    "match_kind": "like",
                    "reason": "Loose match",
                },
            ],
        },
    )

    decision = run_match_selection("SN74HC595N", client=bridge)

    tiers = {cand.ce_id: cand.tier for cand in decision.results}
    assert tiers[20] == MatchTier.TIER_1
    assert tiers[21] == MatchTier.TIER_2
    assert tiers[22] == MatchTier.TIER_3
    assert decision.needs_review is True


def test_invalid_input_raises() -> None:
    bridge = FakeBridge(
        state_payload={"features": {"search_match_kind": True, "normalization_rules_version": "v1"}},
        responses={},
    )
    with pytest.raises(LinkerInputError):
        run_match_selection("   ", client=bridge)


def test_feature_guard() -> None:
    bridge = FakeBridge(state_payload={"features": {}}, responses={})
    with pytest.raises(LinkerFeatureError):
        run_match_selection("LM358", client=bridge)

