"""
mdb_api.py  –  thin, typed wrapper around AWG_COMPLEX.mdb

Features
────────
• Connect / close (context-manager friendly)
• CRUD for complexes and sub-components
• Duplicate complex (deep copy, no PK collisions)
• Simple searches (by name or LIKE pattern)
• Auto-validation helpers (pin names, function IDs)

Only dependency:  pyodbc
───────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import importlib.resources
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple, Union, Sequence

from codecs import BOM_UTF16_BE, BOM_UTF16_LE, BOM_UTF8

import pyodbc
import re
from datetime import datetime

# ─── schema constants ────────────────────────────────────────────────
DRIVER    = r"{Microsoft Access Driver (*.mdb, *.accdb)}"
MASTER_T  = "tabCompDesc"
DETAIL_T  = "detCompDesc"
FUNC_T    = "tabFunction"

PK_MASTER = "IDCompDesc"
PK_DETAIL = "IDSubComponent"

NAME_COL  = "Name"

# pinnable columns order preference
PIN_COLUMNS = [f"Pin{c}" for c in "ABCDEFGH"] + ["PinS"]

# alias table
ALIAS_T   = "tabCompAlias"
# heuristic for foreign key discovery within alias table
FK_REGEX  = re.compile(r"id.*comp", re.I)


def _clean(val):
    if isinstance(val, bytes):
        for enc in ("utf-16-le", "utf-16-be", "utf-8", "cp1252", "latin-1"):
            try:
                return val.decode(enc)
            except UnicodeDecodeError:
                continue
    return val


# ─── simple domain objects ───────────────────────────────────────────
@dataclass
class SubComponent:
    id_sub_component: Optional[int]
    id_function: int
    value: str = ""
    id_unit: int | None = None
    tol_p: float | None = None
    tol_n: float | None = None
    force_bits: int | None = None
    pins: Dict[str, int] | None = None       # {"A":4,"B":5,…}

    # internal – flatten to SQL row (without PK)
    def _flatten(self, fk_master: int) -> Tuple[List[str], List[Any]]:
        cols   = [PK_MASTER, "IDFunction", "Value",
                  "IDUnit", "TolP", "TolN", "ForceBits"]
        vals   = [fk_master, self.id_function, self.value,
                  self.id_unit, self.tol_p, self.tol_n, self.force_bits]

        for name, num in (self.pins or {}).items():
            if name.upper() not in "ABCDEFGH S":
                raise ValueError(f"Illegal pin '{name}'")
            cols.append(f"Pin{name.upper()}")
            vals.append(num)
        return cols, vals


@dataclass
class ComplexDevice:
    id_comp_desc: Optional[int]
    name: str
    total_pins: int
    subcomponents: List[SubComponent]
    # list of alternative PNs (can be empty)
    aliases: List[str] | None = None


# ─── main API class ──────────────────────────────────────────────────
class MDB:
    """
    Friendly wrapper around the Access database.  Use as

        with MDB("AWG_COMPLEX.mdb") as db:
            for cx in db.list_complexes():
                print(cx)
    """

    # ── init / context mgr ─────────────────────────────────────────
    def __init__(self, file: Union[str, Path]):
        self.path = Path(file).resolve()
        self._conn = pyodbc.connect(
            rf"DRIVER={DRIVER};DBQ={self.path}", autocommit=False
        )

    def __enter__(self):  # context-manager support
        return self

    def __exit__(self, exc_type, *_):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()
        self._conn.close()

    # ── utility ----------------------------------------------------
    def _cur(self):
        return self._conn.cursor()

    # ------------------------------------------------------------ utils
    def _alias_schema(self, cur):
        """
        Return (fk_col, alias_col, pk_col or None) for tabCompAlias.
        Heuristics:
          • FK  : exact 'IDCompDesc' if present, else first matching FK_REGEX
          • ALIAS: first column matching ('Alias','AltPN','Alternative','PN','PartNumber','Name') that is not FK/PK
          • PK  : first column that looks like an auto id: startswith 'ID' and contains 'Alias'/'Alt'
        Raises if table not found or ambiguous.
        """
        try:
            cur.execute(f"SELECT TOP 1 * FROM {ALIAS_T}")
        except Exception as e:
            raise RuntimeError(f"Alias table '{ALIAS_T}' not found: {e}")

        cols = [d[0] for d in cur.description]

        # FK column
        fk_col = PK_MASTER if PK_MASTER in cols else None
        if not fk_col:
            fks = [c for c in cols if FK_REGEX.match(c or "")]
            fk_col = fks[0] if fks else None
        if not fk_col:
            raise RuntimeError(f"Could not find FK column to {MASTER_T} in {ALIAS_T}")

        # PK (optional)
        pk_candidates = [
            c for c in cols if str(c).lower().startswith("id") and ("alias" in str(c).lower() or "alt" in str(c).lower())
        ]
        pk_col = pk_candidates[0] if pk_candidates else None

        # Alias text column
        preferred = [
            "Alias",
            "AliasPN",
            "AltPN",
            "AlternativePN",
            "AltPart",
            "PN",
            "PartNumber",
            "AltName",
            "Name",
        ]
        alias_col = None
        for name in preferred:
            if name in cols and name not in (fk_col, pk_col):
                alias_col = name
                break
        if not alias_col:
            rest = [c for c in cols if c not in (fk_col, pk_col)]
            alias_col = rest[0] if rest else None
        if not alias_col:
            raise RuntimeError(f"Could not identify alias text column in {ALIAS_T}")

        return fk_col, alias_col, pk_col

    # ------------------------------------------------------- alias API
    def get_aliases(self, comp_id: int) -> List[str]:
        """Return all alternative PNs (aliases) for a complex."""
        cur = self._cur()
        fk_col, alias_col, _ = self._alias_schema(cur)
        cur.execute(
            f"SELECT [{alias_col}] FROM {ALIAS_T} WHERE [{fk_col}]=? ORDER BY [{alias_col}]",
            comp_id,
        )
        return [_clean(r[0]).strip() for r in cur.fetchall() if (r and r[0] not in (None, ""))]

    def set_aliases(self, comp_id: int, aliases: List[str]):
        """
        Replace aliases for the complex with the provided list.
        Aliases are trimmed; blanks/duplicates are ignored.
        """
        aliases = [a.strip() for a in (aliases or []) if a and a.strip()]
        aliases = sorted(dict.fromkeys(aliases))  # unique, stable order

        cur = self._cur()
        fk_col, alias_col, _ = self._alias_schema(cur)
        cur.execute(f"DELETE FROM {ALIAS_T} WHERE [{fk_col}]=?", comp_id)
        if aliases:
            cols_sql = f"[{fk_col}],[{alias_col}]"
            qm_sql = "?,?"
            for a in aliases:
                cur.execute(
                    f"INSERT INTO {ALIAS_T} ({cols_sql}) VALUES ({qm_sql})", comp_id, _clean(a)
                )

    # ── lookup helpers --------------------------------------------
    def list_complexes(self) -> list[tuple[int, str, int]]:
        """
        Return [(CompID, CompName, SubCount), …] using Access-friendly SQL.
        Note: we intentionally do NOT join tabFunction here (it caused driver
        errors) and the UI only needs ID/Name/SubCount.
        """
        cur = self._cur()
        sql = (
            "SELECT "
            "  m.[IDCompDesc] AS CompID, "
            "  m.[Name]       AS CompName, "
            "  COUNT(d.[IDSubComponent]) AS SubCount "
            "FROM [tabCompDesc] AS m "
            "LEFT JOIN [detCompDesc] AS d "
            "  ON m.[IDCompDesc] = d.[IDCompDesc] "
            "GROUP BY m.[IDCompDesc], m.[Name] "
            "ORDER BY m.[IDCompDesc]"
        )
        cur.execute(sql)
        rows = cur.fetchall()
        # Normalize types and Nones
        return [(int(cid), str(name or ""), int(subs or 0)) for cid, name, subs in rows]



    def search_complexes(self, pattern: str) -> List[Tuple[int, str]]:
        cur = self._cur()
        like = pattern.replace("*", "%")
        cur.execute(
            f"SELECT {PK_MASTER},{NAME_COL} FROM {MASTER_T} WHERE {NAME_COL} LIKE ?",
            like,
        )
        return cur.fetchall()

    def list_functions(self) -> List[Tuple[int, str]]:
        """Return (IDFunction, Name) pairs."""
        cur = self._cur()
        cur.execute("SELECT IDFunction, Name FROM tabFunction ORDER BY Name")
        return cur.fetchall()

    # ── getters ----------------------------------------------------
    def get_complex(self, comp_id: int) -> ComplexDevice:
        cur = self._cur()
        cur.execute(
            f"SELECT * FROM {MASTER_T} WHERE {PK_MASTER}=?", comp_id
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(f"Complex ID {comp_id} not found")
        master_cols = [d[0] for d in cur.description]
        m = {k: _clean(v) for k, v in dict(zip(master_cols, row)).items()}

        cur.execute(
            f"SELECT * FROM {DETAIL_T} WHERE {PK_MASTER}=? ORDER BY {PK_DETAIL}",
            comp_id,
        )
        det_cols = [d[0] for d in cur.description]
        subs = []
        for r in cur.fetchall():
            d = {k: _clean(v) for k, v in dict(zip(det_cols, r)).items()}
            pins = {
                c[3:]: d[c]
                for c in PIN_COLUMNS
                if c in d and d[c] not in (None, 0, "")
            }
            subs.append(
                SubComponent(
                    d[PK_DETAIL],
                    d["IDFunction"],
                    d.get("Value") or "",
                    d.get("IDUnit"),
                    d.get("TolP"),
                    d.get("TolN"),
                    d.get("ForceBits"),
                    pins or None,
                )
            )
        # aliases (alternative PNs)
        try:
            aliases = self.get_aliases(comp_id)
        except RuntimeError:
            aliases = []

        return ComplexDevice(m[PK_MASTER], m[NAME_COL], m.get("TotalPinNumber", 0), subs, aliases)

    # ── creators ---------------------------------------------------
    def create_complex(self, cx: ComplexDevice) -> int:
        cur = self._cur()

        # Optional but safe: nudge master PK to MAX+1 (prevents odd jumps)
        try:
            self._reseed_to_max_plus_one(cur, MASTER_T, PK_MASTER)
        except Exception:
            pass

        cur.execute(
            f"INSERT INTO {MASTER_T} (Name, TotalPinNumber) VALUES (?,?)",
            cx.name,
            cx.total_pins,
        )
        cur.execute("SELECT @@IDENTITY")
        new_id = int(cur.fetchone()[0])

        if cx.subcomponents:
            # Optional: nudge detail PK too before the batch insert
            try:
                self._reseed_to_max_plus_one(cur, DETAIL_T, PK_DETAIL)
            except Exception:
                pass
            for sub in cx.subcomponents:
                cols, vals = sub._flatten(new_id)
                sub_id = self._insert_sub(cur, DETAIL_T, cols, vals)
                sub.id_sub_component = sub_id

        # write aliases if provided
        if getattr(cx, "aliases", None):
            self.set_aliases(new_id, cx.aliases or [])

        return new_id

    def duplicate_complex(self, src_id: int, new_name: str) -> int:
        """Deep-copy master + sub rows.  Returns new master ID."""
        cx = self.get_complex(src_id)
        cx.id_comp_desc = None
        cx.name = new_name
        return self.create_complex(cx)

    def add_complex(self, cx: ComplexDevice) -> int:
        """Insert *cx* and return its new ID.

        This is an alias for :meth:`create_complex` maintained for backwards
        compatibility with the old API.
        """
        return self.create_complex(cx)

    def _reseed_to_max_plus_one(self, cur, table: str, col: str) -> None:
        """Set AutoNumber seed to MAX(col)+1 for *table*. Safe no-op on failure."""
        cur.execute(f"SELECT MAX({col}) AS mx FROM {table}")
        row = cur.fetchone()
        mx = int(row.mx or 0)
        seed = mx + 1
        try:
            cur.execute(f"ALTER TABLE {table} ALTER COLUMN {col} COUNTER ({seed}, 1)")
        except Exception:
            # Some drivers or states may not allow reseeding — ignore quietly.
            pass

    def _update_sub(self, cur, comp_id: int, sub_id: int, sub: SubComponent) -> None:
        """UPDATE a detCompDesc row while preserving its IDSubComponent."""
        # Bracket column names to avoid Access reserved words issues (e.g., Value)
        set_cols = [
            f"[IDFunction] = ?",
            f"[Value] = ?",
            f"[IDUnit] = ?",
            f"[TolP] = ?",
            f"[TolN] = ?",
            f"[ForceBits] = ?",
        ]
        set_vals = [
            int(sub.id_function),
            sub.value,
            None if sub.id_unit is None else int(sub.id_unit),
            None if sub.tol_p   is None else float(sub.tol_p),
            None if sub.tol_n   is None else float(sub.tol_n),
            None if sub.force_bits is None else int(sub.force_bits),
        ]

        # Pins: accept whatever the caller provided (A..H numeric, S may be str/bytes)
        pins = sub.pins or {}
        for name, val in pins.items():
            key = name.upper().strip()
            if key not in set(list("ABCDEFGH") + ["S"]):
                raise ValueError(f"Illegal pin '{name}'")
            colname = f"Pin{key}"
            set_cols.append(f"[{colname}] = ?")
            set_vals.append(val)

        sql = (
            f"UPDATE {DETAIL_T} SET {', '.join(set_cols)} "
            f"WHERE [{PK_MASTER}] = ? AND [{PK_DETAIL}] = ?"
        )
        set_vals.extend([int(comp_id), int(sub_id)])
        cur.execute(sql, *set_vals)

    # ── modifiers --------------------------------------------------
    def update_complex(self, comp_id: int, updated: ComplexDevice | None = None, **fields):
        """
        Update a complex. If `updated` is provided:
        • UPDATE master row (name, total pins)
        • UPDATE overlapping detail rows *in place* (preserve IDSubComponent)
        • INSERT any new rows (optionally reseeding to MAX+1 first)
        • DELETE surplus rows
        If `fields` are provided (and `updated` is None), behave as before.
        """
        cur = self._cur()
        aliases_from_fields = fields.pop("aliases", None)

        # Raw field update path (unchanged)
        if updated is None:
            if not fields:
                # Still allow alias-only updates
                if aliases_from_fields is not None:
                    self.set_aliases(comp_id, aliases_from_fields)
                return
            sql = ", ".join(f"[{k}]=?" for k in fields)
            vals = list(fields.values()) + [comp_id]
            cur.execute(f"UPDATE {MASTER_T} SET {sql} WHERE {PK_MASTER}=?", *vals)
            if aliases_from_fields is not None:
                self.set_aliases(comp_id, aliases_from_fields)
            return

        # 1) Update master
        cur.execute(
            f"UPDATE {MASTER_T} SET Name=?, TotalPinNumber=? WHERE {PK_MASTER}=?",
            updated.name, int(updated.total_pins), int(comp_id)
        )

        # 2) Fetch existing detail IDs (stable order)
        cur.execute(
            f"SELECT {PK_DETAIL} FROM {DETAIL_T} WHERE {PK_MASTER}=? ORDER BY {PK_DETAIL} ASC",
            int(comp_id),
        )
        existing_ids = [int(r[0]) for r in cur.fetchall()]
        new_subs = list(updated.subcomponents or [])

        n_exist = len(existing_ids)
        n_new = len(new_subs)
        n_upd = min(n_exist, n_new)

        # 3) UPDATE overlapping rows in place (preserve PKs)
        for i in range(n_upd):
            self._update_sub(cur, comp_id, existing_ids[i], new_subs[i])

        # 4) INSERT any additional rows
        if n_new > n_exist:
            try:
                self._reseed_to_max_plus_one(cur, DETAIL_T, PK_DETAIL)
            except Exception:
                pass
            for sub in new_subs[n_exist:]:
                cols, vals = sub._flatten(comp_id)
                new_id = self._insert_sub(cur, DETAIL_T, cols, vals)
                sub.id_sub_component = new_id

        # 5) DELETE any surplus rows
        if n_exist > n_new:
            extra_ids = existing_ids[n_new:]
            qmarks = ",".join("?" for _ in extra_ids)
            cur.execute(
                f"DELETE FROM {DETAIL_T} WHERE {PK_MASTER}=? AND {PK_DETAIL} IN ({qmarks})",
                int(comp_id), *extra_ids
            )

        # 6) Update aliases if provided on object
        if getattr(updated, "aliases", None) is not None:
            self.set_aliases(comp_id, updated.aliases or [])

    def delete_complex(self, comp_id: int, cascade: bool = True):
        cur = self._cur()
        if cascade:
            cur.execute(f"DELETE FROM {DETAIL_T} WHERE {PK_MASTER}=?", comp_id)
        cur.execute(f"DELETE FROM {MASTER_T} WHERE {PK_MASTER}=?", comp_id)

    # sub-components
    def add_sub(self, comp_id: int, sub: SubComponent) -> int:
        cur = self._cur()
        cols, vals = sub._flatten(comp_id)
        new_id = self._insert_sub(cur, DETAIL_T, cols, vals)
        sub.id_sub_component = new_id
        return new_id

    def update_sub(self, sub_id: int, **fields):
        if not fields:
            return
        sql = ", ".join(f"[{k}]=?" for k in fields)
        vals = list(fields.values()) + [sub_id]
        self._cur().execute(f"UPDATE {DETAIL_T} SET {sql} WHERE {PK_DETAIL}=?", *vals)

    def delete_sub(self, sub_id: int):
        self._cur().execute(f"DELETE FROM {DETAIL_T} WHERE {PK_DETAIL}=?", sub_id)

    def save_subset_to_mdb(
        self,
        target_path: Union[str, Path],
        comp_ids: Sequence[int],
        template_path: Optional[Path] = None,
    ) -> Path:
        """Export a subset of complexes into a fresh MDB at ``target_path``."""

        normalized: list[int] = []
        seen: set[int] = set()
        for raw in comp_ids:
            try:
                cid = int(raw)
            except Exception:
                continue
            if cid <= 0 or cid in seen:
                continue
            seen.add(cid)
            normalized.append(cid)
        if not normalized:
            raise ValueError("comp_ids must contain at least one positive integer")

        pn_names: list[str] = []
        for cid in normalized:
            device = self.get_complex(cid)
            name = str(getattr(device, "name", "") or "").strip()
            if not name:
                raise LookupError(f"Complex {cid} has no name")
            pn_names.append(name)

        from .pn_exporter import export_pn_to_mdb

        target = Path(target_path).expanduser()

        if template_path is not None:
            candidate = Path(template_path).expanduser()
        else:
            files_fn = getattr(importlib.resources, "files", None)
            if files_fn is not None:
                resource = files_fn("complex_editor.assets") / "Empty_mdb.mdb"
                with importlib.resources.as_file(resource) as asset_path:
                    candidate = Path(asset_path)
            else:  # pragma: no cover - legacy Python fallback
                with importlib.resources.path("complex_editor.assets", "Empty_mdb.mdb") as asset_path:  # type: ignore[attr-defined]
                    candidate = Path(asset_path)

        if not candidate.exists() or candidate.stat().st_size <= 0:
            raise FileNotFoundError(str(candidate))

        result = export_pn_to_mdb(
            self.path,
            candidate,
            target,
            pn_names,
            comp_ids=normalized,
        )
        return Path(result.target_path)

    # ── internals --------------------------------------------------
    def _insert_sub(
        self,
        cur,
        table: str,
        cols: Sequence[str],
        vals: Sequence[Any],
    ) -> int:
        logger = logging.getLogger("complex_editor.db.mdb_api.insert")
        fk = next((v for c, v in zip(cols, vals) if c == PK_MASTER), None)

        col_list = list(cols)
        val_list = list(vals)

        def _preview(pcols: Sequence[str], pvals: Sequence[Any]) -> list[tuple[str, str, str]]:
            items: list[tuple[str, str, str]] = []
            for c, v in zip(pcols, pvals):
                rep = repr(v)
                if len(rep) > 200:
                    rep = rep[:200] + "..."
                items.append((c, type(v).__name__, rep))
            return items

        original_preview = _preview(col_list, val_list)

        try:
            coerced_cols, coerced_vals, coercions = _validate_and_coerce_for_access(
                cur,
                table,
                col_list,
                val_list,
            )
        except DataMismatch as exc:
            logger.warning(
                "INSERT prepare failed table=%s fk=%s cols=%s vals=%s error=%s",
                table,
                fk,
                ",".join(col_list),
                original_preview,
                str(exc),
            )
            raise

        logger.debug(
            "INSERT prepare table=%s fk=%s cols=%s vals=%s",
            table,
            fk,
            ",".join(coerced_cols),
            _preview(coerced_cols, coerced_vals),
        )
        logger.debug("coercions=%s", coercions)

        sql_cols = ", ".join(f"[{c}]" for c in coerced_cols)
        sql_qm = ", ".join("?" for _ in coerced_vals)

        try:
            cur.execute(
                f"INSERT INTO {table} ({sql_cols}) VALUES ({sql_qm})",
                *coerced_vals,
            )
            cur.execute("SELECT @@IDENTITY")
            new_id = int(cur.fetchone()[0])
        except pyodbc.DataError as exc:  # type: ignore[name-defined]
            message = " ".join(str(part) for part in getattr(exc, "args", ()))
            if "22018" in message or "type mismatch" in message.lower():
                logger.warning(
                    "INSERT prepare failed table=%s fk=%s cols=%s vals=%s error=%s",
                    table,
                    fk,
                    ",".join(col_list),
                    original_preview,
                    message,
                )
                raise DataMismatch(f"{table} insert failed: {message}") from exc
            raise

        logger.debug("INSERT committed table=%s fk=%s new_id=%s", table, fk, new_id)
        return new_id


# ---------------------------------------------------------------------------
# Access type probing and value coercion
# ---------------------------------------------------------------------------
from typing import Any, Sequence, Tuple, List, Dict  # re-exported type hints for helpers


class DataMismatch(ValueError):
    pass


def _table_schema(cur, table: str) -> Dict[str, Dict[str, Any]]:
    """
    Return {col_name_lower: {"type": <odbc/sql type>, "nullable": bool, "column_size": int|None,
                             "decimal_digits": int|None, "data_type_name": str}} using cur.columns().
    Normalize names to lowercase.
    """
    cols: Dict[str, Dict[str, Any]] = {}
    try:
        rows = list(cur.columns(table=table))
    except Exception:
        # Fallback: try querying one row to capture description
        try:
            cur.execute(f"SELECT TOP 1 * FROM {table}")
            desc = cur.description or []
            for d in desc:
                name = str(d[0])
                cols[name.lower()] = {
                    "type": None,
                    "nullable": True,
                    "column_size": None,
                    "decimal_digits": None,
                    "data_type_name": "",
                }
            return cols
        except Exception:
            return cols
    for r in rows:
        name = str(getattr(r, "column_name", getattr(r, "COLUMN_NAME", "")) or "").strip()
        if not name:
            continue
        data_type = getattr(r, "data_type", getattr(r, "DATA_TYPE", None))
        raw_type_name = getattr(r, "type_name", getattr(r, "TYPE_NAME", ""))
        type_name = str(raw_type_name or "").lower()
        column_size = getattr(r, "column_size", getattr(r, "COLUMN_SIZE", None))
        decimal_digits = getattr(r, "decimal_digits", getattr(r, "DECIMAL_DIGITS", None))
        nullable_val = getattr(r, "nullable", getattr(r, "NULLABLE", None))
        is_nullable = True
        try:
            is_nullable = bool(int(nullable_val)) if nullable_val is not None else True
        except Exception:
            is_nullable = True
        cols[name.lower()] = {
            "type": data_type,
            "nullable": is_nullable,
            "column_size": int(column_size) if column_size not in (None, "") else None,
            "decimal_digits": int(decimal_digits) if decimal_digits not in (None, "") else None,
            "data_type_name": type_name,
        }
    return cols


def _detect_text_encoding(data: bytes) -> str:
    if data.startswith(BOM_UTF16_LE) or data.startswith(BOM_UTF16_BE):
        return "utf-16"
    if data.startswith(BOM_UTF8):
        return "utf-8-sig"

    window = data[:200]
    stripped = window.lstrip()
    lower = stripped.lower()
    if lower.startswith(b"<?xml"):
        header_end = lower.find(b"?>")
        header = lower if header_end == -1 else lower[:header_end]
        if b"encoding" in header and b"utf-16" in header:
            return "utf-16-le"

    return "utf-8"


def _validate_and_coerce_for_access(
    cur,
    table: str,
    cols: Sequence[str],
    vals: Sequence[Any],
) -> Tuple[Sequence[str], Sequence[Any], List[Dict[str, Any]]]:
    """
    For each (col,val), look up schema. Apply rules:
      - Numeric (INTEGER/SMALLINT/TINYINT/BIGINT/DOUBLE/DECIMAL):
          "" or " " -> None
          "123" -> int
          "12.3" -> float
          bool -> 0/1
      - Yes/No (BIT/BOOLEAN): True/False or "0"/"1"/"true"/"false" -> 0/1
      - Date/Time: ISO-like strings -> parsed datetime; otherwise None if empty
      - Text/VARCHAR/MEMO: ensure <= column_size (truncate if needed and record action "truncate")
    Build coercions list: [{"col":..., "expected":..., "given_type":..., "action":"none|to_int|to_float|bool_to_int|empty_to_null|truncate|parse_datetime|error"}]
    If an uncoercible mismatch remains, raise DataMismatch with details.
    Return (cols, coerced_vals, coercions).
    """

    schema = _table_schema(cur, table)

    def _is_numeric(type_name: str) -> bool:
        t = type_name.lower()
        numeric_tokens = [
            "int",
            "integer",
            "double",
            "decimal",
            "single",
            "float",
            "byte",
            "currency",
            "numeric",
        ]
        return any(token in t for token in numeric_tokens)

    def _is_boolean(type_name: str) -> bool:
        t = type_name.lower()
        return "bit" in t or "yes/no" in t or "bool" in t

    def _is_datetime(type_name: str) -> bool:
        t = type_name.lower()
        return "date" in t or "time" in t

    coerced: List[Any] = []
    actions: List[Dict[str, Any]] = []
    for c, v in zip(cols, vals):
        meta = schema.get(c.lower(), {})
        type_name = str(meta.get("data_type_name") or meta.get("type") or "")
        type_lower = type_name.lower()
        action = "none"
        expected = type_name or "unknown"
        given_type = type(v).__name__

        is_numeric = _is_numeric(type_lower)
        is_boolean = _is_boolean(type_lower)
        is_datetime = _is_datetime(type_lower)

        try:
            if is_numeric:
                if v in ("", " "):
                    v2 = None
                    action = "empty_to_null"
                elif isinstance(v, bool):
                    v2 = 1 if v else 0
                    action = "bool_to_int"
                elif isinstance(v, (int, float)):
                    v2 = v
                elif isinstance(v, str):
                    s = v.strip()
                    if s == "":
                        v2 = None
                        action = "empty_to_null"
                    elif re.fullmatch(r"[-+]?\d+", s or ""):
                        v2 = int(s)
                        action = "to_int"
                    elif re.fullmatch(r"[-+]?\d*\.\d+", s or ""):
                        v2 = float(s)
                        action = "to_float"
                    else:
                        raise DataMismatch(f"Unparseable numeric for {c}: {v!r}")
                else:
                    raise DataMismatch(f"Numeric expected for {c}, got {type(v).__name__}")
                coerced.append(v2)
            elif is_boolean:
                if v in ("", " ", None):
                    v2 = None
                    action = "empty_to_null"
                elif isinstance(v, bool):
                    v2 = 1 if v else 0
                    action = "bool_to_int"
                elif isinstance(v, (int, float)):
                    v2 = 1 if float(v) != 0.0 else 0
                    action = "to_int"
                elif isinstance(v, str):
                    s = v.strip().lower()
                    if s in ("1", "true", "yes", "y"):
                        v2 = 1
                        action = "to_int"
                    elif s in ("0", "false", "no", "n"):
                        v2 = 0
                        action = "to_int"
                    elif s == "":
                        v2 = None
                        action = "empty_to_null"
                    else:
                        raise DataMismatch(f"Boolean expected for {c}, got {v!r}")
                else:
                    raise DataMismatch(f"Boolean expected for {c}, got {type(v).__name__}")
                coerced.append(v2)
            elif is_datetime:
                if v in ("", " "):
                    v2 = None
                    action = "empty_to_null"
                elif isinstance(v, datetime):
                    v2 = v
                elif isinstance(v, str):
                    s = v.strip()
                    if not s:
                        v2 = None
                        action = "empty_to_null"
                    else:
                        # Try common ISO-like formats
                        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                            try:
                                v2 = datetime.strptime(s, fmt)
                                action = "parse_datetime"
                                break
                            except Exception:
                                v2 = None
                        if action != "parse_datetime" and v2 is None:
                            raise DataMismatch(f"Datetime expected for {c}, got {v!r}")
                else:
                    raise DataMismatch(f"Datetime expected for {c}, got {type(v).__name__}")
                coerced.append(v2)
            else:
                if v is None:
                    s2 = None
                elif isinstance(v, str):
                    s2 = v
                elif isinstance(v, bytes):
                    encoding = _detect_text_encoding(v)
                    try:
                        s2 = v.decode(encoding)
                    except UnicodeDecodeError:
                        s2 = v.decode(encoding, errors="replace")
                    action = "bytes_to_str"
                else:
                    s2 = str(v)
                    if action == "none":
                        action = "to_str"

                max_len = meta.get("column_size")
                if (
                    isinstance(s2, str)
                    and isinstance(max_len, int)
                    and max_len > 0
                    and len(s2) > max_len
                ):
                    s2 = s2[:max_len]
                    action = f"{action}+truncate" if action not in ("none", "truncate") else "truncate"
                coerced.append(s2)
        except DataMismatch as dm:
            preview = repr(v)
            if len(preview) > 200:
                preview = preview[:200] + "..."
            raise DataMismatch(f"{table}.{c} expected {expected} got {given_type} value={preview}") from dm
        finally:
            actions.append({
                "col": c,
                "expected": expected,
                "given_type": given_type,
                "action": action,
            })

    return cols, coerced, actions





# ─── quick CLI demo (run `python mdb_api.py your.mdb`) ───────────────
if __name__ == "__main__":  # pragma: no cover
    import argparse
    import textwrap
    import json

    p = argparse.ArgumentParser(
        description="Tiny interactive test-shell for mdb_api",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples
            --------
              # list complexes
              python mdb_api.py db.mdb list

              # duplicate ID 12 as 'MY_COPY'
              python mdb_api.py db.mdb dup 12 MY_COPY

              # dump complex 12 as JSON
              python mdb_api.py db.mdb show 12
            """
        ),
    )
    p.add_argument("file")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")
    sh = sub.add_parser("show")
    sh.add_argument("id", type=int)

    dp = sub.add_parser("dup")
    dp.add_argument("src_id", type=int)
    dp.add_argument("new_name")

    args = p.parse_args()

    with MDB(args.file) as db:
        if args.cmd == "list":
            for cid, name in db.list_complexes():
                print(f"{cid:4}  {name}")
        elif args.cmd == "show":
            cx = db.get_complex(args.id)
            print(json.dumps(cx, default=lambda o: o.__dict__, indent=2))
        elif args.cmd == "dup":
            nid = db.duplicate_complex(args.src_id, args.new_name)
            print(f"Duplicated → ID {nid}")

