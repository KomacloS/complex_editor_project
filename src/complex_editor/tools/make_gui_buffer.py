#!/usr/bin/env python3
"""
make_gui_buffer.py — export MDB contents to a Codex/GUI-friendly JSON buffer.

Usage examples
--------------
# dump everything to tools/buffer.json
python tools/make_gui_buffer.py C:/path/to/main_db.mdb --out tools/buffer.json

# dump only complexes whose names match pattern (Access LIKE; * and ? wildcards)
python tools/make_gui_buffer.py C:/path/to/main_db.mdb --like "74*" --out tools/buffer.json

# dump a few specific IDs
python tools/make_gui_buffer.py C:/path/to/main_db.mdb --ids 4970 4971 --out tools/buffer.json

# write one JSON per complex into a directory
python tools/make_gui_buffer.py C:/path/to/main_db.mdb --per-file tools/buffer_dir
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# --- make sure we can import project code no matter where this runs ---
try:
    from complex_editor.db.mdb_api import MDB, SubComponent, ComplexDevice  # type: ignore
except Exception:  # pragma: no cover - fallback for ad-hoc runs
    ROOT = Path(__file__).resolve().parents[1]  # project root
    SRC = ROOT / "src"
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from complex_editor.db.mdb_api import MDB, SubComponent, ComplexDevice  # type: ignore


log = logging.getLogger("make_gui_buffer")


# ---------- buffer schema (simple, stable, GUI/Codex-friendly) ----------
@dataclass
class BufSubComponent:
    id: Optional[int]
    id_function: int
    function_name: str
    value: Optional[str]  # coerced to string (or None)
    id_unit: Optional[int]
    tol_p: Optional[float]
    tol_n: Optional[float]
    force_bits: Optional[int]
    pins: Dict[str, str]  # map pins like {"A":"1","B":"2","S":"13"}

@dataclass
class BufComplex:
    id: int
    name: str
    total_pins: int
    pins: List[str]                 # ["1","2",...,"N"]
    subcomponents: List[BufSubComponent]

@dataclass
class BufferDoc:
    version: int
    generated_at: str               # ISO8601 UTC
    source_mdb: str                 # absolute path to MDB
    function_map: Dict[str, str]    # {"1":"RES","2":"CAP",...}
    complexes: List[BufComplex]


# ---------- helpers ----------
def _coerce_str_or_none(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val)
    return s if s != "" else None


def _func_map(db: MDB) -> Dict[int, str]:
    try:
        return {int(fid): str(name) for fid, name in db.list_functions()}
    except Exception:
        log.exception("Failed to list functions; continuing with empty map")
        return {}


def _pins_list(total_pins: int) -> List[str]:
    total = int(total_pins or 0)
    return [str(i) for i in range(1, total + 1)]


def _serialize_sub(sc: SubComponent, func_map: Dict[int, str]) -> BufSubComponent:
    fname = func_map.get(int(sc.id_function), f"Function {sc.id_function}")
    # pins as strings for GUI/Codex friendliness
    pin_map = {str(k): str(v) for k, v in (sc.pins or {}).items()}
    return BufSubComponent(
        id=sc.id_sub_component if getattr(sc, "id_sub_component", None) is not None else None,
        id_function=int(sc.id_function),
        function_name=fname,
        value=_coerce_str_or_none(getattr(sc, "value", None)),
        id_unit=getattr(sc, "id_unit", None),
        tol_p=getattr(sc, "tol_p", None),
        tol_n=getattr(sc, "tol_n", None),
        force_bits=getattr(sc, "force_bits", None),
        pins=pin_map,
    )


def _serialize_complex(cx: ComplexDevice, func_map: Dict[int, str]) -> BufComplex:
    total = int(getattr(cx, "total_pins", 0) or 0)
    return BufComplex(
        id=int(getattr(cx, "id_comp_desc")),  # PK
        name=str(getattr(cx, "name", "")),
        total_pins=total,
        pins=_pins_list(total),
        subcomponents=[_serialize_sub(sc, func_map) for sc in (getattr(cx, "subcomponents", []) or [])],
    )


def _select_ids(db: MDB, ids: List[int] | None, like: Optional[str], limit: Optional[int]) -> List[Tuple[int, str]]:
    """
    Return a list of (id, name) pairs to dump.
    - If ids provided: use those (validate existence).
    - elif like provided: use search_complexes(like).
    - else: use list_complexes().
    """
    pairs: List[Tuple[int, str]] = []

    if ids:
        for cid in ids:
            try:
                cx = db.get_complex(int(cid))
                pairs.append((int(cx.id_comp_desc), str(cx.name)))
            except Exception:
                log.warning("ID %s not found or unreadable; skipping", cid)
        return pairs

    if like:
        try:
            res = db.search_complexes(like)
            # search_complexes returns [(id, name), ...]
            pairs = [(int(cid), str(name)) for cid, name in res]
        except Exception:
            log.exception("search_complexes failed; falling back to list_complexes()")
            like = None  # fall through to default

    if not like:
        rows = db.list_complexes()
        # rows may be (id, name, nsubs) or (id, name, func, nsubs)
        for row in rows:
            cid, name = row[0], row[1]
            pairs.append((int(cid), str(name)))

    if limit is not None and limit >= 0:
        pairs = pairs[: int(limit)]
    return pairs


# ---------- main export ----------
def dump_buffer(mdb_path: Path, out_file: Optional[Path], per_file_dir: Optional[Path],
                ids: List[int] | None, like: Optional[str], limit: Optional[int]) -> None:
    mdb_path = mdb_path.resolve()
    with MDB(mdb_path) as db:
        fmap = _func_map(db)
        id_name_pairs = _select_ids(db, ids, like, limit)

        if per_file_dir:
            per_file_dir.mkdir(parents=True, exist_ok=True)

        complexes: List[BufComplex] = []
        for cid, _name in id_name_pairs:
            cx = db.get_complex(cid)
            buf = _serialize_complex(cx, fmap)

            if per_file_dir:
                single = {
                    "version": 1,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "source_mdb": str(mdb_path),
                    "function_map": {str(k): v for k, v in fmap.items()},
                    "complex": asdict(buf),
                }
                (per_file_dir / f"complex_{buf.id}.json").write_text(
                    json.dumps(single, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            else:
                complexes.append(buf)

        if not per_file_dir:
            doc = BufferDoc(
                version=1,
                generated_at=datetime.now(timezone.utc).isoformat(),
                source_mdb=str(mdb_path),
                function_map={str(k): v for k, v in fmap.items()},
                complexes=complexes,
            )
            assert out_file is not None, "--out is required when not using --per-file"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(json.dumps(asdict(doc), ensure_ascii=False, indent=2), encoding="utf-8")

        log.info("Export complete: %s complexes", len(id_name_pairs))


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Export MDB contents to a GUI/Codex-friendly JSON buffer")
    p.add_argument("mdb", type=Path, help="Path to the Access .mdb file")
    gsel = p.add_argument_group("Selection")
    gsel.add_argument("--ids", type=int, nargs="*", help="Explicit complex IDs to export")
    gsel.add_argument("--like", type=str, help="Access LIKE pattern (e.g. '74*')")
    gsel.add_argument("--limit", type=int, help="Limit number of complexes")
    gout = p.add_argument_group("Output")
    gout.add_argument("--out", type=Path, help="Path to single JSON buffer file (required unless --per-file)")
    gout.add_argument("--per-file", type=Path, help="Directory to write one JSON per complex")

    p.add_argument("--verbose", "-v", action="count", default=0, help="Increase logging verbosity")
    args = p.parse_args(argv)

    lvl = logging.WARNING if args.verbose == 0 else logging.INFO if args.verbose == 1 else logging.DEBUG
    logging.basicConfig(level=lvl, format="%(levelname)s %(message)s")

    if not args.per_file and not args.out:
        p.error("Either --out (single file) or --per-file (directory) must be provided")

    try:
        dump_buffer(args.mdb, args.out, args.per_file, args.ids, args.like, args.limit)
        return 0
    except Exception:
        log.exception("Failed to export buffer")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
