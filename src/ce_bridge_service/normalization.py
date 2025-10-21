"""Utilities for normalizing part numbers and explaining applied rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

from complex_editor.config.loader import PnNormalizationConfig

NORMALIZATION_RULES_VERSION = "v1"


@dataclass(slots=True)
class NormalizationResult:
    """Result of applying the configured normalization rules to a value."""

    original: str
    normalized: str
    rule_ids: List[str]
    descriptions: List[str]


class PartNumberNormalizer:
    """Apply configured normalization rules to part numbers and aliases."""

    def __init__(self, config: PnNormalizationConfig | None = None) -> None:
        self._config = config or PnNormalizationConfig()
        self._case_mode = (self._config.case or "").strip().lower() or "upper"
        if self._case_mode not in {"upper", "lower", "none"}:
            self._case_mode = "upper"
        self._remove_chars = tuple(self._config.remove_chars or ())
        self._remove_table = str.maketrans("", "", "".join(self._remove_chars))
        self._suffix_map = [
            (self._apply_case(token), token)
            for token in (self._config.ignore_suffixes or ())
            if token
        ]

    @property
    def config(self) -> PnNormalizationConfig:
        return self._config

    def _apply_case(self, value: str) -> str:
        if self._case_mode == "upper":
            return value.upper()
        if self._case_mode == "lower":
            return value.lower()
        return value

    def normalize(self, value: str) -> NormalizationResult:
        original = value or ""
        working = original.strip()
        rule_ids: List[str] = []
        descriptions: List[str] = []

        cased = self._apply_case(working)
        if cased != working:
            rule_ids.append("rule.case_fold")
            if self._case_mode == "upper":
                descriptions.append("uppercased input")
            elif self._case_mode == "lower":
                descriptions.append("lowercased input")
            else:
                descriptions.append("adjusted case")
            working = cased
        else:
            working = cased

        for suffix_key, display in self._suffix_map:
            if not suffix_key:
                continue
            while working.endswith(suffix_key):
                working = working[: -len(suffix_key)]
                rule_ids.append(f"rule.strip_suffix.{display}")
                descriptions.append(f"ignored suffix '{display}'")

        translated = working.translate(self._remove_table) if self._remove_chars else working
        if translated != working:
            rule_ids.append("rule.strip_punct")
            descriptions.append("removed punctuation")
            working = translated
        else:
            working = translated

        normalized = working.strip()
        return NormalizationResult(
            original=original,
            normalized=normalized,
            rule_ids=rule_ids,
            descriptions=descriptions,
        )

    @staticmethod
    def merge_descriptions(*results: Sequence[NormalizationResult]) -> List[str]:
        """Combine descriptions from multiple normalization results."""

        seen: set[str] = set()
        ordered: List[str] = []
        for result in results:
            for description in result.descriptions:
                if description and description not in seen:
                    seen.add(description)
                    ordered.append(description)
        return ordered
