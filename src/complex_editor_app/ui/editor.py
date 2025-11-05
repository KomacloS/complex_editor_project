"""Complex editor dialog implementation."""
from __future__ import annotations

import configparser
import json
import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional, Tuple

try:  # optional drag and drop treeview
    from ttkwidgets import TreeviewDnD  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    TreeviewDnD = None

from ..core.models import Catalog, Complex, Subcomponent
from ..core.pins import PinParseError, Row, parse_pin_field, validate_pins
from ..core.validation import FieldError, parameter_summary, validate_complex
from .delegates import MacroComboDelegate
from .params import ParameterDialog
from .tooltips import Tooltip
from .widgets import get_user_data_dir

ERROR_BG = "#ffe6e6"
CONFIG_FILE = "layout.ini"


class ComplexEditor(tk.Toplevel):
    """Non-modal editor for a single complex."""

    def __init__(
        self,
        parent: tk.Tk,
        catalog: Catalog,
        complex_obj: Complex,
        on_saved: Callable[[Complex], None],
        summary_callback: Callable[[Complex, Dict[str, str]], None],
    ) -> None:
        super().__init__(parent)
        self.title(f"Edit {complex_obj.part_number}")
        self.parent = parent
        self.catalog = catalog
        self.original = complex_obj
        self.working = replace(complex_obj)
        cloned_rows: List[Subcomponent] = []
        for row in complex_obj.subcomponents:
            copy_row = replace(row)
            copy_row.parameters = json.loads(json.dumps(row.parameters))
            cloned_rows.append(copy_row)
        self.working.subcomponents = cloned_rows
        self.on_saved = on_saved
        self.summary_callback = summary_callback
        self.config_path = get_user_data_dir() / CONFIG_FILE
        self.error_cells: Dict[Tuple[str, str], str] = {}
        self.summary_tooltips: Dict[str, str] = {}
        self._tooltip: Optional[Tooltip] = None

        self.geometry("1000x600")
        self.minsize(900, 520)
        self._load_layout()

        container = ttk.PanedWindow(self, orient=tk.VERTICAL)
        container.pack(fill=tk.BOTH, expand=True)

        form_frame = ttk.Frame(container, padding=12)
        grid_frame = ttk.Frame(container, padding=12)
        container.add(form_frame, weight=1)
        container.add(grid_frame, weight=3)
        self.paned = container

        self._build_form(form_frame)
        self._build_grid(grid_frame)
        self._build_buttons()
        self._bind_shortcuts()
        self._refresh_tree()
        self._update_summary()
        self._update_save_state()
        self.part_number.trace_add("write", lambda *_: self._update_save_state())
        self.pin_count.trace_add("write", lambda *_: (self._update_pin_headings(), self._revalidate_all_pins(), self._update_summary()))

    # ------------------------------------------------------------------
    def _load_layout(self) -> None:
        self.config = configparser.ConfigParser()
        if self.config_path.exists():
            try:
                self.config.read(self.config_path)
                geom = self.config.get("layout", "geometry", fallback=None)
                if geom:
                    self.geometry(geom)
            except Exception:
                pass

    def _save_layout(self) -> None:
        self.config.setdefault("layout", {})
        self.config["layout"]["geometry"] = self.geometry()
        if hasattr(self, "paned"):
            self.config["layout"]["paned_ratio"] = str(self.paned.sashpos(0))
        self.config_path.write_text(self.config_to_string(), encoding="utf-8")

    def config_to_string(self) -> str:
        from io import StringIO

        buffer = StringIO()
        self.config.write(buffer)
        return buffer.getvalue()

    # ------------------------------------------------------------------
    def _build_form(self, frame: ttk.Frame) -> None:
        ttk.Label(frame, text="Part Number").grid(row=0, column=0, sticky="w")
        self.part_number = tk.StringVar(value=self.working.part_number)
        ttk.Entry(frame, textvariable=self.part_number).grid(row=0, column=1, sticky="ew")

        ttk.Label(frame, text="Alternate PNs").grid(row=1, column=0, sticky="nw")
        self.alt_pns = tk.Text(frame, height=3)
        self.alt_pns.insert("1.0", "\n".join(self.working.alternate_part_numbers))
        self.alt_pns.grid(row=1, column=1, sticky="ew")

        ttk.Label(frame, text="Aliases").grid(row=2, column=0, sticky="nw")
        self.aliases = tk.Text(frame, height=3)
        self.aliases.insert("1.0", "\n".join(self.working.aliases))
        self.aliases.grid(row=2, column=1, sticky="ew")

        ttk.Label(frame, text="Pin Count").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.pin_count = tk.IntVar(value=self.working.pin_count)
        ttk.Spinbox(frame, from_=1, to=512, textvariable=self.pin_count, width=8).grid(row=0, column=3, sticky="w")

        frame.columnconfigure(1, weight=1)

    def _build_grid(self, frame: ttk.Frame) -> None:
        tree_class = getattr(TreeviewDnD, "TreeviewDnD", None) if TreeviewDnD else ttk.Treeview
        if not tree_class:
            tree_class = ttk.Treeview
        self.columns = ("position", "macro", "pin_a", "pin_b", "pin_c", "pin_d", "summary")
        self.tree = tree_class(frame, columns=self.columns, show="headings")
        headings = {
            "position": "#",
            "macro": "Macro",
            "pin_a": "Pin A",
            "pin_b": "Pin B",
            "pin_c": "Pin C",
            "pin_d": "Pin D",
            "summary": "Parameters",
        }
        for name, label in headings.items():
            self.tree.heading(name, text=label)
            if name == "position":
                self.tree.column(name, width=50, anchor=tk.CENTER)
            elif name == "macro":
                self.tree.column(name, width=200, anchor=tk.W, stretch=True)
            elif name == "summary":
                self.tree.column(name, width=240, anchor=tk.W, stretch=True)
            else:
                self.tree.column(name, width=120, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self._edit_cell)
        self.tree.bind("<Button-3>", self._context_menu)
        self.tree.bind("<Motion>", self._on_motion)
        self.tree.bind("<Leave>", lambda _e: self._hide_tooltip())

        self.macro_delegate = MacroComboDelegate(
            self.tree,
            values_provider=lambda: self.catalog.names(),
            commit=self._commit_macro,
            cancel=lambda: None,
        )
        self._update_pin_headings()
        self.after(50, self._restore_paned_ratio)

    def _build_buttons(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill=tk.X, pady=8, padx=12)
        ttk.Button(bar, text="Add Row", command=self._add_row).pack(side=tk.LEFT)
        ttk.Button(bar, text="Remove Row", command=self._remove_row).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bar, text="Duplicate Row", command=self._duplicate_row).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bar, text="Clear Pins", command=self._clear_pins).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bar, text="Reset Params", command=self._reset_params).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bar, text="Move Up", command=lambda: self._move_row(-1)).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(bar, text="Move Down", command=lambda: self._move_row(1)).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(bar, text="Edit Parameters", command=self._open_params).pack(side=tk.LEFT, padx=(12, 0))

        self.save_btn = ttk.Button(bar, text="Save", command=self._save)
        self.save_btn.pack(side=tk.RIGHT)
        ttk.Button(bar, text="Cancel", command=self._cancel).pack(side=tk.RIGHT, padx=(0, 8))

    def _bind_shortcuts(self) -> None:
        bindings = {
            "<Return>": self._edit_cell,
            "<F2>": self._edit_cell,
            "<Control-d>": lambda e: self._duplicate_row(),
            "<Delete>": lambda e: self._remove_row(),
            "<Control-Up>": lambda e: self._move_row(-1),
            "<Control-Down>": lambda e: self._move_row(1),
            "<Control-e>": lambda e: self._open_params(),
            "<Escape>": lambda e: self._hide_tooltip(),
        }
        for sequence, handler in bindings.items():
            self.tree.bind(sequence, handler)

    # ------------------------------------------------------------------
    def _selected_item(self) -> Optional[str]:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _add_row(self) -> None:
        position = len(self.working.subcomponents) + 1
        self.working.subcomponents.append(Subcomponent(position=position, macro=""))
        self._refresh_tree()
        self._update_save_state()

    def _remove_row(self) -> None:
        item = self._selected_item()
        if not item:
            return
        index = int(self.tree.set(item, "position")) - 1 if "position" in self.tree.set(item) else self.tree.index(item)
        if 0 <= index < len(self.working.subcomponents):
            del self.working.subcomponents[index]
            self._reindex()
            self._refresh_tree()
            self._update_save_state()

    def _duplicate_row(self) -> None:
        item = self._selected_item()
        if not item:
            return
        index = self.tree.index(item)
        source = self.working.subcomponents[index]
        clone = Subcomponent(
            position=index + 2,
            macro=source.macro,
            pin_a=source.pin_a,
            pin_b=source.pin_b,
            pin_c=source.pin_c,
            pin_d=source.pin_d,
            parameters=json.loads(json.dumps(source.parameters)),
        )
        self.working.subcomponents.insert(index + 1, clone)
        self._reindex()
        self._refresh_tree()
        self._update_save_state()

    def _clear_pins(self) -> None:
        for row in self._selected_rows():
            row.pin_a = row.pin_b = row.pin_c = row.pin_d = ""
        self._refresh_tree()
        self._update_save_state()

    def _reset_params(self) -> None:
        for row in self._selected_rows():
            row.parameters.clear()
        self._refresh_tree()
        self._update_save_state()

    def _move_row(self, delta: int) -> None:
        item = self._selected_item()
        if not item:
            return
        index = self.tree.index(item)
        new_index = max(0, min(len(self.working.subcomponents) - 1, index + delta))
        if new_index == index:
            return
        row = self.working.subcomponents.pop(index)
        self.working.subcomponents.insert(new_index, row)
        self._reindex()
        self._refresh_tree(select_index=new_index)
        self._update_save_state()

    def _selected_rows(self) -> List[Subcomponent]:
        rows = []
        for item in self.tree.selection():
            rows.append(self.working.subcomponents[self.tree.index(item)])
        return rows

    def _reindex(self) -> None:
        for idx, row in enumerate(self.working.subcomponents, start=1):
            row.position = idx

    def _edit_cell(self, event: Optional[tk.Event] = None) -> None:
        item = self._selected_item()
        if not item:
            return
        column_id = self.tree.identify_column(event.x) if event else "#2"
        column_name = self._column_name(column_id)
        if column_name == "macro":
            data = self.tree.set(item, "macro")
            self.macro_delegate.begin(item, "macro", initial=data)
        elif column_name.startswith("pin_"):
            self._edit_pin(item, column_name)
        elif column_name == "summary":
            self._open_params()

    def _edit_pin(self, item: str, column: str) -> None:
        bbox = self.tree.bbox(item, column)
        if not bbox:
            return
        x, y, width, height = bbox
        value = self.tree.set(item, column)
        entry = ttk.Entry(self.tree)
        entry.insert(0, value)
        entry.select_range(0, tk.END)
        entry.focus_set()
        entry.place(x=x, y=y, width=width, height=height)

        def commit(event: Optional[tk.Event] = None) -> None:
            text = entry.get()
            entry.destroy()
            self._commit_pin(item, column, text)

        def cancel(_event: Optional[tk.Event] = None) -> None:
            entry.destroy()

        entry.bind("<Return>", commit)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", lambda e: commit())

    def _commit_macro(self, value: str) -> None:
        item = self._selected_item()
        if not item:
            return
        index = self.tree.index(item)
        row = self.working.subcomponents[index]
        row.macro = value
        macro = self.catalog.get(value)
        if not macro:
            self.error_cells[(item, "macro")] = "Macro not found"
            row.parameters.clear()
        else:
            row.parameters = {k: v for k, v in row.parameters.items() if k in macro.parameters}
            self.error_cells.pop((item, "macro"), None)
        self._refresh_tree(select_index=index)
        self._update_save_state()

    def _commit_pin(self, item: str, column: str, value: str) -> None:
        index = self.tree.index(item)
        row = self.working.subcomponents[index]
        setattr(row, column, value)
        self.tree.set(item, column, value)
        self._revalidate_all_pins()
        self._update_summary()
        self._update_save_state()

    def _update_error_tags(self) -> None:
        self.tree.tag_configure("error", background=ERROR_BG)
        for item in self.tree.get_children():
            has_error = any(key[0] == item for key in self.error_cells)
            tags = list(self.tree.item(item, "tags"))
            if has_error and "error" not in tags:
                tags.append("error")
            elif not has_error and "error" in tags:
                tags.remove("error")
            self.tree.item(item, tags=tags)

    def _on_motion(self, event: tk.Event) -> None:
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            self._hide_tooltip()
            return
        row_id = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        column_name = self._column_name(column_id)
        message = None
        for (item, col), text in self.error_cells.items():
            if item == row_id and col == column_name:
                message = text
                break
        if not message and column_name == "summary":
            message = self.summary_tooltips.get(row_id)
        if message:
            self._show_tooltip(event, message)
        else:
            self._hide_tooltip()

    def _show_tooltip(self, event: tk.Event, text: str) -> None:
        if self._tooltip:
            self._tooltip.hide()
        self._tooltip = Tooltip(widget=self.tree, text=text)
        self._tooltip.show(event)

    def _hide_tooltip(self) -> None:
        if self._tooltip:
            self._tooltip.hide()
            self._tooltip = None

    def _context_menu(self, event: tk.Event) -> None:
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Edit Parameters", command=self._open_params)
        menu.add_command(label="Duplicate", command=self._duplicate_row)
        menu.add_command(label="Clear Pins", command=self._clear_pins)
        menu.add_command(label="Reset Params", command=self._reset_params)
        menu.add_separator()
        menu.add_command(label="Move Up", command=lambda: self._move_row(-1))
        menu.add_command(label="Move Down", command=lambda: self._move_row(1))
        menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------
    def _refresh_tree(self, select_index: Optional[int] = None) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.summary_tooltips.clear()
        for row in self.working.subcomponents:
            macro = self.catalog.get(row.macro)
            summary = ""
            tooltip = ""
            if macro:
                summary, tooltip = parameter_summary(macro, row.parameters)
            item = self.tree.insert(
                "",
                tk.END,
                values=(
                    row.position,
                    row.macro,
                    row.pin_a,
                    row.pin_b,
                    row.pin_c,
                    row.pin_d,
                    summary,
                ),
            )
            if tooltip:
                self.summary_tooltips[item] = tooltip
        self._revalidate_all_pins()
        if select_index is not None:
            item = self.tree.get_children()[select_index]
            self.tree.selection_set(item)
            self.tree.focus(item)
        self._update_summary()
        self._update_error_tags()

    def _open_params(self) -> None:
        item = self._selected_item()
        if not item:
            return
        index = self.tree.index(item)
        row = self.working.subcomponents[index]
        macro = self.catalog.get(row.macro)
        if not macro:
            return
        dialog = ParameterDialog(self, macro, row.parameters)
        result = dialog.show()
        if not result:
            return
        row.parameters = result.full
        self._refresh_tree(select_index=index)

    def _update_summary(self) -> None:
        pins_used = 0
        errors = len(self.error_cells)
        for row in self.working.subcomponents:
            for value in (row.pin_a, row.pin_b, row.pin_c, row.pin_d):
                try:
                    pins_used += len(parse_pin_field(value))
                except Exception:
                    errors += 1
        stats = {
            "Pin Count": str(self.pin_count.get()),
            "Pins Used": str(pins_used),
            "Pins Free": str(max(0, self.pin_count.get() - pins_used)),
            "Rows": str(len(self.working.subcomponents)),
            "Errors": str(errors),
        }
        self.summary_callback(self.working, stats)

    def _collect_complex(self) -> Complex:
        pn = self.part_number.get().strip().upper()
        alt = [line.strip() for line in self.alt_pns.get("1.0", tk.END).splitlines() if line.strip()]
        aliases = [line.strip() for line in self.aliases.get("1.0", tk.END).splitlines() if line.strip()]
        complex_obj = replace(
            self.working,
            part_number=pn,
            alternate_part_numbers=alt,
            aliases=aliases,
            pin_count=self.pin_count.get(),
        )
        return complex_obj

    def _save(self) -> None:
        complex_obj = self._collect_complex()
        errors: List[FieldError] = validate_complex(complex_obj, self.catalog)
        pin_rows = []
        for row in complex_obj.subcomponents:
            pin_rows.append(
                Row(
                    index=row.position,
                    macro=row.macro,
                    pins={
                        "A": parse_pin_field(row.pin_a),
                        "B": parse_pin_field(row.pin_b),
                        "C": parse_pin_field(row.pin_c),
                        "D": parse_pin_field(row.pin_d),
                    },
                )
            )
        pin_errors = validate_pins(pin_rows, complex_obj.pin_count)
        issues = [f"Row {err.row_index}: {err.column} – {err.message}" for err in pin_errors][:10]
        if len(issues) < 10:
            remaining = 10 - len(issues)
            issues.extend([f"{err.field}: {err.message}" for err in errors][:remaining])
        if issues:
            messagebox.showerror(
                "Cannot Save – Fix Validation Errors",
                "\n".join(issues),
                parent=self,
            )
            return
        self.on_saved(complex_obj)
        self.destroy()

    def _cancel(self) -> None:
        self.destroy()

    def _update_save_state(self) -> None:
        pn_ok = bool(self.part_number.get().strip())
        has_macro = any(row.macro for row in self.working.subcomponents)
        self.save_btn.state(["!disabled"] if pn_ok and has_macro and not self.error_cells else ["disabled"])

    def _column_name(self, column_id: str) -> str:
        if column_id.startswith("#"):
            index = int(column_id[1:]) - 1
            if 0 <= index < len(self.columns):
                return self.columns[index]
        return column_id

    def _revalidate_all_pins(self) -> None:
        items = list(self.tree.get_children())
        leg_lookup = {"A": "pin_a", "B": "pin_b", "C": "pin_c", "D": "pin_d"}
        for key in list(self.error_cells.keys()):
            if key[1].startswith("pin_") or key[1] == "macro":
                self.error_cells.pop(key, None)
        row_objects: List[Row] = []
        for item, row in zip(items, self.working.subcomponents):
            if not row.macro:
                self.error_cells[(item, "macro")] = "Macro required"
            elif not self.catalog.get(row.macro):
                self.error_cells[(item, "macro")] = f"Unknown macro '{row.macro}'"
            pins_for_row: Dict[str, List[int]] = {}
            for leg, attr in leg_lookup.items():
                try:
                    pins_for_row[leg] = parse_pin_field(getattr(row, attr))
                except PinParseError as exc:
                    self.error_cells[(item, attr)] = str(exc)
                    pins_for_row[leg] = []
            row_objects.append(Row(index=row.position, macro=row.macro, pins=pins_for_row))
        pin_errors = validate_pins(row_objects, max(self.pin_count.get(), 1))
        for err in pin_errors:
            idx = err.row_index - 1
            if 0 <= idx < len(items):
                column = leg_lookup.get(err.column, "pin_a")
                self.error_cells[(items[idx], column)] = err.message
        self._update_error_tags()
        self._update_save_state()

    def _update_pin_headings(self) -> None:
        limit = self.pin_count.get()
        for leg in ("A", "B", "C", "D"):
            column = f"pin_{leg.lower()}"
            self.tree.heading(column, text=f"Pin {leg} (1..{limit})")

    def _restore_paned_ratio(self) -> None:
        try:
            ratio = self.config.getint("layout", "paned_ratio")
        except Exception:
            ratio = None
        if ratio is not None:
            try:
                self.paned.sashpos(0, ratio)
            except Exception:
                pass

    def destroy(self) -> None:  # type: ignore[override]
        self._save_layout()
        super().destroy()


__all__ = ["ComplexEditor"]
