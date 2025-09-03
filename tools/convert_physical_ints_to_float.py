# tools/convert_physical_ints_to_float.py
import re
import sys
from pathlib import Path
import shutil
import yaml

# Parameters that look like physical measurements -> should allow decimals
PHYS = re.compile(
    r"(?:Volt(?:age)?(?:_[A-Za-z])?|"
    r"Current(?:_[A-Za-z])?|"
    r"Res(?:istance|Par|Ser)?(?:_[A-Za-z])?|"
    r"Cap(?:acit|acitance|Par)?(?:_[A-Za-z])?|"
    r"Induct(?:ance)?(?:_[A-Za-z])?|"
    r"Time(?:out)?|Delay|"
    r"Frequency|Power|"
    r"Value(?:ON|OFF)?|"
    r"Tol(?:P|N)|"
    r"Threshold|Level|Gain|Slope)$",
    re.IGNORECASE,
)

def default_yaml_path() -> Path:
    # script: <repo>/tools/convert_physical_ints_to_float.py
    # yaml:   <repo>/src/complex_editor/resources/function_param_allowed.yaml
    p = Path(__file__).resolve().parents[1] / "src" / "complex_editor" / "resources" / "function_param_allowed.yaml"
    return p

def main(yaml_path: Path):
    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML not found: {yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    changed = 0
    touched = []

    # Walk: { MacroName: { ParamName: spec } }
    for macro, params in (doc or {}).items():
        if not isinstance(params, dict):
            continue
        for pname, spec in params.items():
            if not isinstance(spec, dict):
                continue
            # Skip enums/strings
            if "enum" in spec:
                continue
            if spec.get("type") == "INT" and PHYS.search(str(pname)):
                spec["type"] = "FLOAT"
                changed += 1
                touched.append(f"{macro}.{pname}")

    if changed == 0:
        print("No changes needed.")
        return

    # Backup
    backup = yaml_path.with_suffix(yaml_path.suffix + ".bak")
    shutil.copy2(yaml_path, backup)

    with yaml_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)

    print(f"Updated {changed} parameters to FLOAT.")
    for s in touched[:25]:
        print("  -", s)
    if len(touched) > 25:
        print(f"  … and {len(touched) - 25} more")
    print(f"Backup written to: {backup}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        ypath = Path(sys.argv[1])
    else:
        ypath = default_yaml_path()
    main(ypath)
