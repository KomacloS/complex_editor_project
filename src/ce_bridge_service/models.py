from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class MatchKind(str, Enum):
    EXACT_PN = "exact_pn"
    EXACT_ALIAS = "exact_alias"
    NORMALIZED_PN = "normalized_pn"
    NORMALIZED_ALIAS = "normalized_alias"
    LIKE = "like"


class ComplexSummary(BaseModel):
    """Search result summary for a complex."""

    id: int
    pn: str
    aliases: List[str] = Field(default_factory=list)
    db_path: Optional[str] = None
    match_kind: Optional[MatchKind] = None
    reason: Optional[str] = None
    normalized_input: Optional[str] = None
    normalized_targets: Optional[List[str]] = None
    rule_ids: Optional[List[str]] = None


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


class ComplexOpenRequest(BaseModel):
    mode: Optional[str] = Field(default="view")


class ComplexCreateResponse(BaseModel):
    id: int
    pn: str
    aliases: List[str] = Field(default_factory=list)
    db_path: Optional[str] = None


class AliasUpdateRequest(BaseModel):
    add: List[str] = Field(default_factory=list)
    remove: List[str] = Field(default_factory=list)


class AliasUpdateResponse(BaseModel):
    id: int
    pn: str
    aliases: List[str] = Field(default_factory=list)
    db_path: str
    updated: Dict[str, List[str]]
    source_hash: str


class HealthResponse(BaseModel):
    ok: bool
    ready: bool
    version: str
    db_path: str
    host: str
    port: int
    auth_required: bool
    headless: bool = False
    allow_headless: bool = False


class ResolvedPart(BaseModel):
    pn: str
    comp_id: int


class MdbExportRequest(BaseModel):
    pns: Optional[List[str]] = None
    comp_ids: Optional[List[int]] = None
    out_dir: str
    mdb_name: str = Field(default="bom_complexes.mdb")
    require_linked: bool = False
    template_path: Optional[str] = None


class MdbExportResponse(BaseModel):
    ok: bool = True
    export_path: str
    exported_comp_ids: List[int] = Field(default_factory=list)
    resolved: List[ResolvedPart] = Field(default_factory=list)
    unlinked: List[str] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)


__all__ = [
    "ComplexSummary",
    "ComplexDetail",
    "ComplexCreateRequest",
    "ComplexOpenRequest",
    "ComplexCreateResponse",
    "AliasUpdateRequest",
    "AliasUpdateResponse",
    "MatchKind",
    "HealthResponse",
    "ResolvedPart",
    "MdbExportRequest",
    "MdbExportResponse",
]
