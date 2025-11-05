"""Persistence helpers for the Complex Editor demo application."""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, replace
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .models import Catalog, Complex, Subcomponent, build_sample_catalog

_LOCK = threading.RLock()


class Repository:
    """Simple JSON backed repository used by the Tkinter demo.

    The implementation is intentionally lightweight: data is stored in a single
    JSON file containing the macro catalog and a list of complexes. The API
    mirrors the subset of operations the UI needs.
    """

    def __init__(self, path: Path, catalog: Optional[Catalog] = None) -> None:
        self.path = path
        self.catalog = catalog or build_sample_catalog()
        self._complex_index: Dict[str, Complex] = {}
        self._load()

    # ------------------------------------------------------------------
    # internal helpers
    def _load(self) -> None:
        if not self.path.exists():
            self._complex_index = {c.identifier: c for c in self._demo_complexes()}
            self.flush()
            return

        with _LOCK:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        complexes: Dict[str, Complex] = {}
        for row in payload.get("complexes", []):
            subcomponents: List[Subcomponent] = []
            for sc in row.get("subcomponents", []):
                subcomponents.append(
                    Subcomponent(
                        position=int(sc.get("position", len(subcomponents) + 1)),
                        macro=sc.get("macro", ""),
                        pin_a=sc.get("pin_a", ""),
                        pin_b=sc.get("pin_b", ""),
                        pin_c=sc.get("pin_c", ""),
                        pin_d=sc.get("pin_d", ""),
                        parameters=dict(sc.get("parameters", {})),
                    )
                )
            complex_obj = Complex(
                identifier=row.get("identifier", row.get("part_number", "")),
                part_number=row.get("part_number", ""),
                alternate_part_numbers=list(row.get("alternate_part_numbers", [])),
                aliases=list(row.get("aliases", [])),
                pin_count=int(row.get("pin_count", 0)),
                subcomponents=subcomponents,
            )
            complexes[complex_obj.identifier] = complex_obj
        self._complex_index = complexes

    # ------------------------------------------------------------------
    def _demo_complexes(self) -> Iterable[Complex]:
        """Return a small set of complexes bundled with the repository."""

        catalog = self.catalog
        resistor = Complex(
            identifier="cmp-100",
            part_number="CMP-100",
            alternate_part_numbers=["CMP-100A"],
            aliases=["demo-board"],
            pin_count=16,
            subcomponents=[
                Subcomponent(
                    position=1,
                    macro="Resistor",
                    pin_a="1",
                    pin_b="2",
                    parameters={"value": 10000.0, "tolerance": "1%"},
                ),
                Subcomponent(
                    position=2,
                    macro="BufferGate",
                    pin_a="3",
                    pin_b="4",
                    parameters={"channels": 2, "schmitt": True},
                ),
            ],
        )

        led_chain = Complex(
            identifier="cmp-200",
            part_number="CMP-200",
            alternate_part_numbers=["CMP-200B"],
            aliases=["indicator"],
            pin_count=12,
            subcomponents=[
                Subcomponent(
                    position=1,
                    macro="LED",
                    pin_a="5",
                    pin_b="6",
                    parameters={"color": "green", "forward_voltage": 2.1},
                ),
                Subcomponent(
                    position=2,
                    macro="LED",
                    pin_a="7",
                    pin_b="8",
                    parameters={"color": "red", "forward_voltage": 1.9},
                ),
            ],
        )

        return (resistor, led_chain)

    # ------------------------------------------------------------------
    # public API
    def list_complexes(self) -> List[Complex]:
        return sorted(self._complex_index.values(), key=lambda c: c.part_number)

    def get_complex(self, identifier: str) -> Optional[Complex]:
        return self._complex_index.get(identifier)

    def upsert_complex(self, complex_obj: Complex) -> Complex:
        with _LOCK:
            self._complex_index[complex_obj.identifier] = replace(complex_obj)
            self.flush()
        return complex_obj

    def flush(self) -> None:
        payload = {
            "complexes": [self._serialize_complex(obj) for obj in self._complex_index.values()],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    def _serialize_complex(self, complex_obj: Complex) -> Dict[str, object]:
        return {
            "identifier": complex_obj.identifier,
            "part_number": complex_obj.part_number,
            "alternate_part_numbers": list(complex_obj.alternate_part_numbers),
            "aliases": list(complex_obj.aliases),
            "pin_count": complex_obj.pin_count,
            "subcomponents": [asdict(sc) for sc in complex_obj.subcomponents],
        }


__all__ = [
    "Repository",
]
