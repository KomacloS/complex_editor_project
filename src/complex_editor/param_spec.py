import importlib.resources
from typing import Dict

import yaml

_yml = (
    importlib.resources.files("complex_editor.resources")
    / "function_param_allowed.yaml"
)
data = yaml.safe_load(_yml.read_text())
if isinstance(data, dict):
    data.pop("version", None)

ALLOWED_PARAMS: Dict[str, Dict] = data
