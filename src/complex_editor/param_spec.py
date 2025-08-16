import importlib.resources
import re
from typing import Dict, Optional

import yaml

_yml = (
    importlib.resources.files("complex_editor.resources")
    / "function_param_allowed.yaml"
)
data = yaml.safe_load(_yml.read_text())
if isinstance(data, dict):
    data.pop("version", None)

ALLOWED_PARAMS: Dict[str, Dict] = data


def normalize_macro_name(name: str) -> str:
    """Return a canonicalised representation of *name*.

    Whitespace is stripped, the name upper–cased and runs of ``[ _-]`` are
    collapsed into a single underscore.  The returned value is intended for
    lookups and should not be displayed to the user.
    """

    return re.sub(r"[ _-]+", "_", str(name).strip().upper())


# Map of normalised canonical macro names to the name as used in the YAML spec
_CANONICAL: Dict[str, str] = {
    normalize_macro_name(key): key for key in ALLOWED_PARAMS.keys()
}

# Optional alias mapping loaded from resources/macro_aliases.yaml.  Each alias
# maps to a canonical YAML key.  Missing file or invalid contents are tolerated.
try:
    _alias_res = (
        importlib.resources.files("complex_editor.resources")
        / "macro_aliases.yaml"
    )
    _alias_data = yaml.safe_load(_alias_res.read_text()) or {}
except FileNotFoundError:  # pragma: no cover - optional resource
    _alias_data = {}

_ALIASES: Dict[str, str] = {}
if isinstance(_alias_data, dict):
    for alias, target in _alias_data.items():
        norm_alias = normalize_macro_name(alias)
        norm_target = normalize_macro_name(target)
        _ALIASES[norm_alias] = _CANONICAL.get(norm_target, target)


def resolve_macro_name(macro_name: str) -> Optional[str]:
    """Resolve *macro_name* to the canonical key used in ``ALLOWED_PARAMS``.

    The lookup is case–insensitive and honours aliases defined in
    ``resources/macro_aliases.yaml``.  If the name cannot be resolved ``None``
    is returned.
    """

    norm = normalize_macro_name(macro_name)
    if norm in _CANONICAL:
        return _CANONICAL[norm]
    if norm in _ALIASES:
        target = _ALIASES[norm]
        return _CANONICAL.get(normalize_macro_name(target), target)
    return None


__all__ = ["ALLOWED_PARAMS", "normalize_macro_name", "resolve_macro_name"]

