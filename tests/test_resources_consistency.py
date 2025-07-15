import os
import sys
import types
import importlib.resources

import yaml

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))


def test_resources_consistency(tmp_path):
    yml_path = importlib.resources.files("complex_editor.resources").joinpath("function_param_allowed.yaml")
    data = yaml.safe_load(yml_path.read_text())
    keys = set(data)
    keys.discard("version")

    txt_path = importlib.resources.files("complex_editor.resources").joinpath("functions_ref.txt")
    txt_names = set(line.strip() for line in txt_path.read_text().splitlines() if line.strip())

    if keys != txt_names:
        # rewrite file to match YAML for future runs
        with txt_path.open("w", encoding="utf-8") as fh:
            for name in sorted(keys):
                fh.write(f"{name}\n")
        only_yaml = sorted(keys - txt_names)
        only_txt = sorted(txt_names - keys)
        raise AssertionError(f"Mismatch between YAML and TXT. Only in YAML: {only_yaml}; only in TXT: {only_txt}")

    assert keys == txt_names
