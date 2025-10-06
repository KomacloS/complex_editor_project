"""FastAPI bridge for Complex Editor."""

from .app import create_app
from .types import BridgeCreateResult

__all__ = ["create_app", "BridgeCreateResult"]
