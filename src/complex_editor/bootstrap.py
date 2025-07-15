from pathlib import Path
import sys


def add_repo_src_to_syspath() -> None:
    """Prepend the repository's src directory to ``sys.path`` if needed."""
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    if src_root.exists() and str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

__all__ = ["add_repo_src_to_syspath"]
