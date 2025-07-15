from __future__ import annotations

from pathlib import Path
import pkgutil

# Include the real package located under src/ so "python -m complex_editor.cli"
# works when the project is not installed.
__path__ = pkgutil.extend_path(__path__, __name__)
_src = Path(__file__).resolve().parent.parent / "src" / __name__
if _src.exists():
    __path__.append(str(_src))

try:
    from .bootstrap import add_repo_src_to_syspath  # type: ignore
except Exception:
    pass
else:
    add_repo_src_to_syspath()
