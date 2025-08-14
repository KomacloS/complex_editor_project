import os, sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from complex_editor.ui.buffer_loader import load_editor_complexes_from_buffer


def test_buffer_preload() -> None:
    path = Path(__file__).resolve().parent.parent / "tools" / "buffer.json"
    import json, tempfile
    data = json.load(path.open())
    with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
        json.dump(data["complexes"], tmp)
        tmp.flush()
        tmp_path = Path(tmp.name)
    complexes = load_editor_complexes_from_buffer(tmp_path)
    found = None
    for cx in complexes:
        for sc in cx.subcomponents:
            if sc.all_macros:
                found = sc
                break
        if found:
            break
    assert found is not None
    assert found.macro_params
