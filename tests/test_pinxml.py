from __future__ import annotations

import os
import sys
import types

# Provide a dummy pyodbc module so import succeeds in CLI
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor import cli  # noqa: E402
from complex_editor.domain import MacroInstance, macro_to_xml  # noqa: E402

EXPECTED_XML = (
    "<?xml version=\"1.0\" encoding=\"utf-16\"?>\n"
    "<R>\n"
    "  <Macros>\n"
    "    <Macro Name=\"GATE\">\n"
    "      <Param Value=\"010101\" Name=\"PathPin_A\" />\n"
    "      <Param Value=\"HLHLHL\" Name=\"PathPin_B\" />\n"
    "    </Macro>\n"
    "  </Macros>\n"
    "</R>"
)


def test_macro_to_xml():
    macro = MacroInstance("GATE", {"PathPin_A": "010101", "PathPin_B": "HLHLHL"})
    out = macro_to_xml(macro)
    assert out.replace("\r\n", "\n") == EXPECTED_XML
    bytes_out = out.encode("utf-16le")
    assert b"\xff\xfe" not in bytes_out


def test_cli_make_pinxml(capsys):
    exit_code = cli.main(
        [
            "make-pinxml",
            "--macro",
            "GATE",
            "--param",
            "PathPin_A=010101",
            "--param",
            "PathPin_B=HLHLHL",
        ]
    )
    assert exit_code == 0
    hex_out = capsys.readouterr().out.strip()
    bytes_out = bytes.fromhex(hex_out)
    xml = bytes_out.decode("utf-16le")
    assert xml.replace("\r\n", "\n") == EXPECTED_XML
