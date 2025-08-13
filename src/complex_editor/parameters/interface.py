from __future__ import annotations

from typing import Any, Dict, Protocol


class MacroParamProvider(Protocol):
    """Pluggable parser/serializer for macro parameters."""

    def parse_params(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Parse raw parameter payload from the buffer."""

    def to_wizard_fields(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Convert parsed params into fields understood by the wizard."""


class NullParamProvider:
    """Default no-op implementation used when no PinS support is present."""

    def parse_params(self, raw: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - trivial
        return {}

    def to_wizard_fields(self, params: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - trivial
        return {}
