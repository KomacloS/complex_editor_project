from base64 import b64decode
from importlib import resources
from pathlib import Path


def write_template(path: Path) -> None:
    """Decode template_b64.TEMPLATE_B64 and write bytes to *path*."""
    from .template_b64 import TEMPLATE_B64
    path.write_bytes(b64decode(TEMPLATE_B64))
