import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

import complex_editor.tools.learn_rules as lr
from complex_editor.domain import MacroDef, MacroParam


def test_cli_writes_rules(tmp_path, monkeypatch):
    buffer = {
        "Complex": {"Name": "C1", "ID": 1},
        "SubComponents": [
            {
                "MacroName": "G_A_T_E",
                "PinMap": {
                    "S": (
                        "<R><Macros><Macro Name='G_A_T_E'>"
                        "<Param Name='Start_Freq' Value='1'/></Macro></Macros></R>"
                    )
                },
            }
        ],
    }
    buf = tmp_path / "buffer.json"
    buf.write_text(json.dumps(buffer), encoding="utf-8")
    out = tmp_path / "rules.json"
    monkeypatch.setattr(
        lr.schema_introspect,
        "discover_macro_map",
        lambda cur: {1: MacroDef(1, "GATE", [MacroParam("StartFreq", "INT", None, None, None)])},
    )
    monkeypatch.setattr(
        sys, "argv", ["learn_rules", "--buffer", str(buf), "--out", str(out)]
    )
    lr.main()
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "G_A_T_E" in data.get("macro_aliases", {})

