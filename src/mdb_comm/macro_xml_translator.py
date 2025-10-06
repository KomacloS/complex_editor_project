from pathlib import Path
from typing import Any, Mapping
import argparse
import logging
from functools import lru_cache

from complex_editor.utils import yaml_adapter as yaml

from complex_editor.util.macro_xml_translator import (
    params_to_xml as _params_to_xml,
    xml_to_params as _xml_to_params,
)

from .macro_selector import load_rules, choose_macro, map_macro_to_function

LOGGER = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parent / "data"
RES_DIR = Path(__file__).resolve().parents[1] / "complex_editor" / "resources"
DEFAULTS_PATH = RES_DIR / "function_param_allowed.yaml"


def _load_yaml(path: str | Path) -> Mapping[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def _load_defaults(path: str | Path = DEFAULTS_PATH) -> Mapping[str, Mapping[str, Any]]:
    """Return mapping of {Function: {Param: default_value}}."""
    data = _load_yaml(path)
    result: dict[str, dict[str, Any]] = {}
    for fname, params in data.items():
        if isinstance(params, Mapping):
            d: dict[str, Any] = {}
            for pname, spec in params.items():
                if isinstance(spec, Mapping) and "default" in spec:
                    d[pname] = spec["default"]
            result[fname] = d
    return result


def _is_default(val: Any, default: Any) -> bool:
    try:
        return float(val) == float(default)
    except (TypeError, ValueError):
        return str(val) == str(default)


def _validate_gate(params: Mapping[str, Any]) -> None:
    """Check that Check_[A-D] match PathPin_[A-D] lengths."""
    def _plen(v: Any) -> int:
        if v is None:
            return 0
        s = str(v)
        return 0 if s in {"", "-1", "-1.0"} else len(s)

    for suf in "ABCD":
        path_len = _plen(params.get(f"PathPin_{suf}"))
        check_len = _plen(params.get(f"Check_{suf}"))
        if path_len == 0 and check_len != 0:
            raise ValueError(f"Check_{suf} without PathPin_{suf}")
        if path_len > 0 and check_len not in (0, path_len):
            raise ValueError(
                f"Check_{suf} length {check_len} does not match PathPin_{suf} length {path_len}"
            )


def params_to_xml(
    params: Mapping[str, Mapping[str, Any]],
    *,
    ctx: Mapping[str, Any] | None = None,
    rules: Mapping[str, Any] | None = None,
    fn_map: Mapping[str, list[str]] | None = None,
) -> bytes:
    """Serialize *params* using macro selection rules."""

    ctx = ctx or {}
    if rules is None:
        rules = load_rules(DATA_DIR / "macro_selection_rules.yaml")
    if fn_map is None:
        fn_map = _load_yaml(DATA_DIR / "function_to_xml_macro_map.yaml")

    defaults = _load_defaults()
    macros = {}
    for fname, pvals in params.items():
        if fname == "GATE":
            _validate_gate(pvals)
        if fname in rules:
            macro = choose_macro(fname, ctx, rules)
            reason = "criteria"
        else:
            cand = (fn_map.get(fname) or [fname])[0]
            macro = cand
            reason = "fallback"
        LOGGER.info("macro-choice", extra={"function": fname, "macro": macro, "reason": reason})
        dvals = defaults.get(fname, {})
        filtered = {
            pname: val
            for pname, val in pvals.items()
            if not (pname in dvals and _is_default(val, dvals[pname]))
        }
        macros[macro] = filtered
    return _params_to_xml(macros)


def xml_to_params(
    xml: bytes | str,
    *,
    inv_map: Mapping[str, list[str]] | None = None,
) -> Mapping[str, Mapping[str, str]]:
    """Parse XML macros into canonical function mapping when possible."""

    if inv_map is None:
        inv_map = _load_yaml(DATA_DIR / "xml_macro_to_function_map.yaml")
    macros = _xml_to_params(xml)
    result = {}
    for mname, params in macros.items():
        fname = map_macro_to_function(mname, inv_map)
        if fname is None:
            funcs = inv_map.get(mname)
            if funcs:
                fname = funcs[0]
                LOGGER.warning("ambiguous-macro-name", extra={"macro": mname, "function": fname})
            else:
                fname = mname
        result[fname] = params
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Translate between params YAML and macro XML")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_xml = sub.add_parser("to-xml", help="convert params YAML to XML")
    p_xml.add_argument("infile")
    p_xml.add_argument("outfile", nargs="?")
    p_xml.add_argument("--ctx", default=DATA_DIR / "macro_selector_context.example.yaml")
    p_xml.add_argument("--rules", default=DATA_DIR / "macro_selection_rules.yaml")
    p_xml.add_argument("--map", dest="map_path", default=DATA_DIR / "function_to_xml_macro_map.yaml")

    p_params = sub.add_parser("to-params", help="convert XML to params YAML")
    p_params.add_argument("infile")
    p_params.add_argument("outfile", nargs="?")
    p_params.add_argument("--ctx", default=DATA_DIR / "macro_selector_context.example.yaml")
    p_params.add_argument("--inv", default=DATA_DIR / "xml_macro_to_function_map.yaml")
    p_params.add_argument("--rules", default=DATA_DIR / "macro_selection_rules.yaml")
    p_params.add_argument("--map", dest="map_path", default=DATA_DIR / "function_to_xml_macro_map.yaml")

    args = parser.parse_args(argv)
    if args.cmd == "to-xml":
        params = _load_yaml(args.infile)
        ctx = _load_yaml(args.ctx)
        rules = load_rules(args.rules)
        fn_map = _load_yaml(args.map_path)
        xml = params_to_xml(params, ctx=ctx, rules=rules, fn_map=fn_map)
        if args.outfile:
            Path(args.outfile).write_bytes(xml)
        else:
            import sys
            sys.stdout.buffer.write(xml)
    else:  # to-params
        xml_data = Path(args.infile).read_bytes()
        inv_map = _load_yaml(args.inv)
        macros = xml_to_params(xml_data, inv_map=inv_map)
        text = yaml.safe_dump(macros, sort_keys=False)
        if args.outfile:
            Path(args.outfile).write_text(text, encoding="utf-8")
        else:
            import sys
            sys.stdout.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
