from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ComplexSummary(BaseModel):
    """Search result summary for a complex."""

    id: int
    name: str
    aliases: List[str] = Field(default_factory=list)
    db_path: str


class ComplexDetail(ComplexSummary):
    """Detailed view of a complex."""

    total_pins: int
    pin_map: Dict[str, Dict[str, object]] = Field(default_factory=dict)
    macro_ids: List[int] = Field(default_factory=list)
    source_hash: str
    updated_at: Optional[str] = None


class ComplexCreateRequest(BaseModel):
    pn: str
    aliases: Optional[List[str]] = None


class ComplexCreateResponse(BaseModel):
    id: int
    db_path: str


class HealthResponse(BaseModel):
    ok: bool
    version: str
    db_path: str
    host: str
    port: int
    auth_required: bool


__all__ = [
    "ComplexSummary",
    "ComplexDetail",
    "ComplexCreateRequest",
    "ComplexCreateResponse",
    "HealthResponse",
]
