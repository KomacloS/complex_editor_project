"""
Integration-tests for mdb_api.MDB

Run with:
    pytest -q test_mdb_api.py --db=AWG_COMPLEX.mdb
The option can point to either .mdb or .accdb.

What is covered
---------------
✓ list & search
✓ load complex + children
✓ duplicate complex      (deep copy, PKs change)
✓ add / update / delete sub-component
✓ update / delete complex
"""

import pyodbc
import pytest
from pathlib import Path
import shutil
import tempfile
import uuid
import re

try:
    pyodbc.connect("DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=:memory:")
except pyodbc.Error:
    pytest.skip("Access ODBC driver not present", allow_module_level=True)

from mdb_api import MDB, ComplexDevice, SubComponent

# ----------------------------------------------------------------------#
# pytest command-line option: --db=path.mdb                              #
# ----------------------------------------------------------------------#
def pytest_addoption(parser):
    parser.addoption(
        "--db", required=True, help="Path to source MDB / ACCDB used for tests"
    )


@pytest.fixture(scope="session")
def db_copy(pytestconfig) -> Path:
    """Copy the original DB to a temp dir so tests never change real data."""
    src = Path(pytestconfig.getoption("--db")).resolve()
    if not src.exists():
        pytest.skip(f"Source DB not found: {src}")
    tmp = Path(tempfile.mkdtemp()) / f"test_{uuid.uuid4().hex}{src.suffix}"
    shutil.copy(src, tmp)
    yield tmp
    # temp dir auto-cleaned by OS


# ----------------------------------------------------------------------#
# helpers                                                               #
# ----------------------------------------------------------------------#
def first_complex_id(db: MDB) -> int:
    return db.list_complexes()[0][0]


def assert_complex_equal(a: ComplexDevice, b: ComplexDevice, *, ignore_ids=True):
    """Deep compare two ComplexDevice objects."""
    attrs = ("name", "total_pins")
    for attr in attrs:
        assert getattr(a, attr) == getattr(b, attr)

    assert len(a.subcomponents) == len(b.subcomponents)
    for sa, sb in zip(a.subcomponents, b.subcomponents):
        if not ignore_ids:
            assert sa.id_sub_component == sb.id_sub_component
        assert sa.id_function == sb.id_function
        assert sa.value == sb.value
        assert sa.tol_p == sb.tol_p
        assert sa.tol_n == sb.tol_n
        assert sa.force_bits == sb.force_bits
        assert (sa.pins or {}) == (sb.pins or {})


# ----------------------------------------------------------------------#
# tests                                                                  #
# ----------------------------------------------------------------------#
def test_duplicate_complex(db_copy: Path):
    with MDB(db_copy) as db:
        src_id = first_complex_id(db)
        src = db.get_complex(src_id)

        new_name = src.name + "_pydup"
        new_id = db.duplicate_complex(src_id, new_name)

        dup = db.get_complex(new_id)

        # names differ, everything else identical
        assert dup.name == new_name
        assert_complex_equal(src, dup)

        # all new sub-component PKs are unique & different from source
        src_sub_ids = {s.id_sub_component for s in src.subcomponents}
        dup_sub_ids = {s.id_sub_component for s in dup.subcomponents}
        assert not src_sub_ids & dup_sub_ids


def test_add_update_delete_sub(db_copy: Path):
    with MDB(db_copy) as db:
        master_id = first_complex_id(db)
        before = db.get_complex(master_id)
        n_before = len(before.subcomponents)

        # add ----------------------------------------------------------
        new_sub = SubComponent(
            None,
            id_function=before.subcomponents[0].id_function,  # reuse a legal function
            value="TEST123",
            pins={"A": 1, "B": 2},
        )
        new_sub_id = db.add_sub(master_id, new_sub)
        assert new_sub_id is not None

        cx_after_add = db.get_complex(master_id)
        assert len(cx_after_add.subcomponents) == n_before + 1

        # update -------------------------------------------------------
        db.update_sub(new_sub_id, Value="UPDATED!", TolP=5.0)
        cx_after_upd = db.get_complex(master_id)
        upd_sub = [s for s in cx_after_upd.subcomponents if s.id_sub_component == new_sub_id][0]
        assert upd_sub.value == "UPDATED!"
        assert upd_sub.tol_p == 5.0

        # delete -------------------------------------------------------
        db.delete_sub(new_sub_id)
        cx_after_del = db.get_complex(master_id)
        assert len(cx_after_del.subcomponents) == n_before


def test_update_and_delete_complex(db_copy: Path):
    with MDB(db_copy) as db:
        # create a throw-away copy to work on
        src_id  = first_complex_id(db)
        temp_id = db.duplicate_complex(src_id, "TMP_DELETE_ME")

        # rename
        db.update_complex(temp_id, Name="TMP_RENAMED", TotalPinNumber=99)
        cx = db.get_complex(temp_id)
        assert cx.name == "TMP_RENAMED"
        assert cx.total_pins == 99

        # delete (cascade)
        db.delete_complex(temp_id, cascade=True)
        with pytest.raises(KeyError):
            db.get_complex(temp_id)


def test_search(db_copy: Path):
    with MDB(db_copy) as db:
        # assume names contain letters+digits; pick first 3 consecutive chars
        _, some_name = db.list_complexes()[0]
        pat = f"%{re.escape(some_name[:3])}%"
        hits = db.search_complexes(pat)
        assert any(n == some_name for _, n in hits)
