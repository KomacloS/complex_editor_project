from __future__ import annotations

from typing import Iterable, Mapping

from .models import AllowlistDocument, BundleChange, BundleDiff, FunctionBundle


class OverlayDiffError(RuntimeError):
    """Raised when bundle normalisation detects invalid data."""


def _soft_change(entry_hash: str, bundle: FunctionBundle) -> bool:
    return entry_hash == bundle.structure_hash


def diff_bundles(
    discovered: Iterable[FunctionBundle],
    document: AllowlistDocument,
) -> BundleDiff:
    """Return :class:`BundleDiff` for *discovered* vs allowlist document."""

    db_map: Mapping[tuple[int, int], FunctionBundle] = {b.identity: b for b in discovered}
    allowed_map = document.entry_map()

    added = {
        ident: bundle
        for ident, bundle in db_map.items()
        if ident not in allowed_map
    }
    removed = {
        ident: entry
        for ident, entry in allowed_map.items()
        if ident not in db_map and entry.active
    }
    changed: dict[tuple[int, int], BundleChange] = {}
    for ident, entry in allowed_map.items():
        bundle = db_map.get(ident)
        if bundle is None:
            continue
        if entry.signature_hash == bundle.signature_hash:
            continue
        change_kind = "soft" if _soft_change(entry.structure_hash, bundle) else "hard"
        changed[ident] = BundleChange(current=entry, discovered=bundle, change_kind=change_kind)

    return BundleDiff(added=added, removed=removed, changed=changed)

