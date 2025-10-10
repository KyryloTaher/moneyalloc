"""Tkinter user interface for managing hierarchical money allocations."""
from __future__ import annotations

import csv
import math
import tkinter as tk
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, Iterable, List, Optional

from .db import AllocationRepository
from .models import (
    Allocation,
    Distribution,
    DistributionEntry,
    DistributionRiskInput,
    canonicalize_time_horizon,
)
from .sample_data import populate_with_sample_data
from .risk_optimizer import (
    ProblemSpec,
    run_risk_equal_optimization,
)


DEFAULT_TIME_HORIZONS: tuple[str, ...] = (
    "1D",
    "1W",
    "2W",
    "1M",
    "3M",
    "6M",
    "1Y",
    "3Y",
    "5Y",
)
ALL_TIME_HORIZONS_OPTION = "All time horizons"

_UNSPECIFIED_CURRENCY_ALIASES: frozenset[str] = frozenset({
    "UNSPECIFIED",
    "NONE",
    "N/A",
    "NA",
})


def horizon_to_years(horizon: str) -> float:
    """Return the duration in years represented by a canonical horizon string."""

    if not horizon:
        raise ValueError("Horizon must be a non-empty string.")

    value_part, unit = horizon[:-1], horizon[-1]
    try:
        value = float(value_part)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid horizon value: {horizon!r}") from exc

    if value <= 0:
        raise ValueError(f"Horizon value must be positive: {horizon!r}")

    if unit == "Y":
        return value
    if unit == "M":
        return value / 12.0
    if unit == "W":
        return value / 52.0
    if unit == "D":
        return value / 365.0

    raise ValueError(f"Unsupported horizon unit: {horizon!r}")


class RiskInputEditor(ttk.LabelFrame):
    """Inline editor that captures risk inputs for required time horizons."""

    _SLEEVES: tuple[tuple[str, str, str], ...] = (
        ("rates", "Government (DV01) yield", "Government tenor"),
        ("tips", "Inflation (BE01) yield", "Inflation tenor"),
        ("credit", "Credit (CS01) yield", "Credit tenor"),
    )

    def __init__(self, master: tk.Widget) -> None:
        super().__init__(master, text="Risk inputs", padding=10)
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True)
        self._vars: dict[tuple[str, str, str, str], tk.StringVar] = {}
        self._status_var = tk.StringVar()
        self._status_label = ttk.Label(
            self,
            textvariable=self._status_var,
            wraplength=720,
            foreground="#aa0000",
            justify="left",
        )
        self._status_label.pack(fill="x", pady=(8, 0))
        self._horizons: dict[str, list[str]] = {}
        self._horizon_signature: dict[str, tuple[str, ...]] = {}
        self._visible = False
        self._pack_options: dict[str, object] = {"fill": "x", "pady": (10, 0)}

    def configure_pack(self, **options: object) -> None:
        """Update geometry options used when displaying the editor."""

        self._pack_options.update(options)

    def hide(self) -> None:
        if self._visible:
            self.pack_forget()
            self._visible = False

    def show(self) -> None:
        if not self._visible:
            self.pack(**self._pack_options)
            self._visible = True

    def clear(self) -> None:
        for child in self._notebook.winfo_children():
            child.destroy()
        self._vars.clear()
        self._horizons = {}
        self._horizon_signature = {}
        self._status_var.set("")

    @staticmethod
    def _display_currency(currency: str) -> str:
        return currency or "Unspecified"

    def set_requirements(
        self,
        horizons_by_currency: dict[str, list[str]],
        initial: Optional[dict[str, dict[str, dict[str, tuple[float, float]]]]] = None,
    ) -> None:
        normalized_horizons = {
            currency: tuple(sorted(dict.fromkeys(horizons)))
            for currency, horizons in horizons_by_currency.items()
        }
        if not normalized_horizons:
            self.clear()
            self.hide()
            return
        if normalized_horizons == self._horizon_signature:
            if initial:
                self._apply_initial_values(initial, only_if_empty=True)
            self.show()
            return

        self.clear()
        self.show()
        self._horizons = {currency: list(values) for currency, values in normalized_horizons.items()}
        self._horizon_signature = normalized_horizons
        initial_data = initial or {}
        for currency in sorted(self._horizons, key=lambda value: value or ""):
            frame = ttk.Frame(self._notebook)
            frame.columnconfigure(tuple(range(1 + 2 * len(self._SLEEVES))), weight=1)
            self._notebook.add(frame, text=self._display_currency(currency))

            ttk.Label(frame, text="Time horizon").grid(row=0, column=0, padx=4, pady=4, sticky="w")
            for col, (_sleeve, yield_label, tenor_label) in enumerate(self._SLEEVES, start=1):
                ttk.Label(frame, text=yield_label).grid(row=0, column=2 * col - 1, padx=4, pady=4)
                ttk.Label(frame, text=f"{tenor_label} (years)").grid(
                    row=0, column=2 * col, padx=4, pady=4
                )

            for row_index, horizon in enumerate(self._horizons[currency], start=1):
                ttk.Label(frame, text=horizon).grid(row=row_index, column=0, sticky="w", padx=4, pady=2)
                for col_index, (sleeve, _yield_label, _tenor_label) in enumerate(
                    self._SLEEVES, start=1
                ):
                    yield_var = tk.StringVar()
                    tenor_var = tk.StringVar()
                    initial_sleeve = (
                        initial_data.get(currency, {})
                        .get(horizon, {})
                        .get(sleeve)
                    )
                    if initial_sleeve:
                        yield_var.set(f"{initial_sleeve[0]:.4f}")
                        tenor_var.set(f"{initial_sleeve[1]:.4f}")
                    else:
                        computed_tenor = horizon_to_years(horizon)
                        tenor_var.set(f"{computed_tenor:.4f}")
                    ttk.Entry(frame, textvariable=yield_var, width=12).grid(
                        row=row_index,
                        column=2 * col_index - 1,
                        padx=4,
                        pady=2,
                    )
                    ttk.Entry(frame, textvariable=tenor_var, width=10).grid(
                        row=row_index,
                        column=2 * col_index,
                        padx=4,
                        pady=2,
                    )
                    self._vars[(currency, horizon, sleeve, "yield")] = yield_var
                    self._vars[(currency, horizon, sleeve, "tenor")] = tenor_var

    def _apply_initial_values(
        self,
        initial: dict[str, dict[str, dict[str, tuple[float, float]]]],
        *,
        only_if_empty: bool = False,
    ) -> None:
        """Populate entry fields using previously captured input values."""

        for currency, horizons in initial.items():
            for horizon, sleeve_data in horizons.items():
                for sleeve, (yield_value, tenor_value) in sleeve_data.items():
                    yield_var = self._vars.get((currency, horizon, sleeve, "yield"))
                    tenor_var = self._vars.get((currency, horizon, sleeve, "tenor"))
                    if yield_var and (not only_if_empty or not yield_var.get().strip()):
                        yield_var.set(f"{yield_value:.4f}")
                    if tenor_var and (not only_if_empty or not tenor_var.get().strip()):
                        tenor_var.set(f"{tenor_value:.4f}")

    def _get_var(self, currency: str, horizon: str, sleeve: str, kind: str) -> tk.StringVar:
        key = (currency, horizon, sleeve, kind)
        if key not in self._vars:
            self._vars[key] = tk.StringVar()
        return self._vars[key]

    def set_status(self, message: str) -> None:
        self._status_var.set(message)

    def collect(self) -> dict[str, dict[str, dict[str, tuple[float, float]]]]:
        if not self._horizons:
            return {}
        data: dict[str, dict[str, dict[str, tuple[float, float]]]] = {}
        for currency, horizons in self._horizons.items():
            currency_data: dict[str, dict[str, tuple[float, float]]] = {}
            for horizon in horizons:
                horizon_data: dict[str, tuple[float, float]] = {}
                for sleeve, _yield_label, _tenor_label in self._SLEEVES:
                    yield_text = self._get_var(currency, horizon, sleeve, "yield").get().strip()
                    tenor_text = self._get_var(currency, horizon, sleeve, "tenor").get().strip()
                    if not yield_text:
                        continue
                    try:
                        yield_value = float(yield_text)
                    except ValueError:
                        raise ValueError(
                            "Yields must be numeric values in the risk inputs section."
                        ) from None
                    if tenor_text:
                        try:
                            tenor_value = float(tenor_text)
                        except ValueError:
                            raise ValueError(
                                "Tenors must be numeric values in the risk inputs section."
                            ) from None
                    else:
                        tenor_value = horizon_to_years(horizon)
                    if tenor_value <= 0:
                        raise ValueError("Tenor values must be positive numbers.")
                    horizon_data[sleeve] = (yield_value, tenor_value)
                if not horizon_data:
                    raise ValueError(
                        "Provide at least one instrument for each time horizon in the risk inputs section."
                    )
                currency_data[horizon] = horizon_data
            if currency_data:
                data[currency] = currency_data
        if not data:
            raise ValueError(
                "Provide at least one instrument to calculate the risk summary."
            )
        self._status_var.set("")
        return data


class RiskInputLibraryTab(ttk.Frame):
    """Standalone editor for managing reusable risk input combinations."""

    _SLEEVE_OPTIONS: tuple[str, ...] = tuple(sleeve for sleeve, *_ in RiskInputEditor._SLEEVES)
    _SLEEVE_LABELS: dict[str, str] = {sleeve: label for sleeve, label, _ in RiskInputEditor._SLEEVES}

    def __init__(
        self,
        master: tk.Misc,
        on_changed: Optional[Callable[[dict[str, dict[str, dict[str, tuple[float, float]]]]], None]] = None,
        initial: Optional[dict[str, dict[str, dict[str, tuple[float, float]]]]] = None,
    ) -> None:
        super().__init__(master, padding=10)
        self._on_changed = on_changed
        self._data: dict[str, dict[str, dict[str, tuple[float, float]]]] = deepcopy(initial or {})
        self._row_mapping: dict[str, tuple[str, str, str]] = {}

        self.currency_var = tk.StringVar()
        self.horizon_var = tk.StringVar()
        self.sleeve_var = tk.StringVar(value=self._SLEEVE_OPTIONS[0])
        self.yield_var = tk.StringVar()
        self.tenor_var = tk.StringVar()
        self.status_var = tk.StringVar()

        self.columnconfigure(0, weight=1)

        instructions = (
            "Build a library of tenor/yield inputs that can be reused when running "
            "risk calculations. Add one row per currency, time horizon and sleeve."
        )
        ttk.Label(self, text=instructions, wraplength=700, justify="left").grid(
            row=0, column=0, sticky="w"
        )

        form = ttk.Frame(self)
        form.grid(row=1, column=0, sticky="ew", pady=(10, 6))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        ttk.Label(form, text="Currency code:").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.currency_var, width=12).grid(
            row=0, column=1, sticky="w", padx=(4, 12)
        )

        ttk.Label(form, text="Time horizon:").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            form,
            textvariable=self.horizon_var,
            values=list(DEFAULT_TIME_HORIZONS),
            width=12,
        ).grid(row=0, column=3, sticky="w", padx=(4, 12))

        ttk.Label(form, text="Sleeve:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            form,
            textvariable=self.sleeve_var,
            values=self._SLEEVE_OPTIONS,
            state="readonly",
            width=12,
        ).grid(row=1, column=1, sticky="w", padx=(4, 12), pady=(6, 0))

        ttk.Label(form, text="Yield (%):").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.yield_var, width=12).grid(
            row=1, column=3, sticky="w", padx=(4, 12), pady=(6, 0)
        )

        ttk.Label(form, text="Tenor (years):").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.tenor_var, width=12).grid(
            row=2, column=1, sticky="w", padx=(4, 12), pady=(6, 0)
        )

        button_row = ttk.Frame(form)
        button_row.grid(row=2, column=2, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Button(button_row, text="Add / update", command=self._add_or_update).pack(
            side="left"
        )
        ttk.Button(button_row, text="Remove selected", command=self._remove_selected).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(button_row, text="Clear all", command=self._clear_all).pack(
            side="left", padx=(6, 0)
        )

        tree_frame = ttk.Frame(self)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        columns = ("currency", "horizon", "sleeve", "yield", "tenor")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            height=12,
        )
        self.tree.heading("currency", text="Currency")
        self.tree.heading("horizon", text="Horizon")
        self.tree.heading("sleeve", text="Sleeve")
        self.tree.heading("yield", text="Yield %")
        self.tree.heading("tenor", text="Tenor (y)")
        self.tree.column("currency", width=110, anchor="center")
        self.tree.column("horizon", width=90, anchor="center")
        self.tree.column("sleeve", width=160, anchor="w")
        self.tree.column("yield", width=90, anchor="e")
        self.tree.column("tenor", width=100, anchor="e")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        ttk.Label(self, textvariable=self.status_var, foreground="#aa0000", anchor="w").grid(
            row=3, column=0, sticky="ew", pady=(6, 0)
        )

        self.rowconfigure(2, weight=1)
        self._refresh_tree()

    def _emit_change(self) -> None:
        if self._on_changed:
            self._on_changed(self.get_data())

    def _refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._row_mapping.clear()
        for currency in sorted(self._data, key=lambda value: value or ""):
            horizons = self._data[currency]
            for horizon in sorted(horizons):
                sleeves = horizons[horizon]
                for sleeve in sorted(sleeves):
                    yield_value, tenor_value = sleeves[sleeve]
                    item_id = f"{currency}\u241f{horizon}\u241f{sleeve}"
                    self.tree.insert(
                        "",
                        "end",
                        iid=item_id,
                        values=(
                            self._display_currency(currency),
                            horizon,
                            self._SLEEVE_LABELS.get(sleeve, sleeve),
                            f"{yield_value:.4f}",
                            f"{tenor_value:.4f}",
                        ),
                    )
                    self._row_mapping[item_id] = (currency, horizon, sleeve)

    @staticmethod
    def _display_currency(currency: str) -> str:
        return RiskInputEditor._display_currency(currency)

    def _add_or_update(self) -> None:
        currency_text = self.currency_var.get().strip().upper()
        currency_key = "" if currency_text in _UNSPECIFIED_CURRENCY_ALIASES else currency_text

        horizon_text = self.horizon_var.get().strip().upper()
        if not horizon_text:
            self.status_var.set("Provide a time horizon (for example 1Y or 6M).")
            return
        try:
            horizon_value = canonicalize_time_horizon(horizon_text)
        except ValueError:
            self.status_var.set(
                "Time horizon must follow the '<number><unit>' pattern (e.g. 1Y, 3M, 6W or 10D)."
            )
            return

        sleeve_value = self.sleeve_var.get().strip()
        if sleeve_value not in self._SLEEVE_OPTIONS:
            self.status_var.set("Select a sleeve before adding the entry.")
            return

        yield_text = self.yield_var.get().strip()
        if not yield_text:
            self.status_var.set("Enter a yield percentage for the selected sleeve.")
            return
        try:
            yield_value = float(yield_text)
        except ValueError:
            self.status_var.set("Yield must be a numeric value.")
            return

        tenor_text = self.tenor_var.get().strip()
        if tenor_text:
            try:
                tenor_value = float(tenor_text)
            except ValueError:
                self.status_var.set("Tenor must be a numeric value in years.")
                return
        else:
            tenor_value = horizon_to_years(horizon_value)

        if tenor_value <= 0:
            self.status_var.set("Tenor must be a positive value.")
            return

        currency_bucket = self._data.setdefault(currency_key, {})
        horizon_bucket = currency_bucket.setdefault(horizon_value, {})
        horizon_bucket[sleeve_value] = (yield_value, tenor_value)

        self.status_var.set("")
        self._refresh_tree()
        self._emit_change()

    def _remove_selected(self) -> None:
        removed = False
        for item_id in list(self.tree.selection()):
            mapping = self._row_mapping.get(item_id)
            if not mapping:
                continue
            currency, horizon, sleeve = mapping
            currency_bucket = self._data.get(currency)
            if not currency_bucket:
                continue
            horizon_bucket = currency_bucket.get(horizon)
            if not horizon_bucket:
                continue
            horizon_bucket.pop(sleeve, None)
            if not horizon_bucket:
                currency_bucket.pop(horizon, None)
            if not currency_bucket:
                self._data.pop(currency, None)
            removed = True
        if removed:
            self.status_var.set("")
            self._refresh_tree()
            self._emit_change()

    def _clear_all(self) -> None:
        if not self._data:
            return
        self._data.clear()
        self._refresh_tree()
        self._emit_change()

    def _on_tree_select(self, event: tk.Event[tk.EventType]) -> None:  # pragma: no cover - UI glue
        selection = self.tree.selection()
        if not selection:
            return
        mapping = self._row_mapping.get(selection[0])
        if not mapping:
            return
        currency, horizon, sleeve = mapping
        yield_value, tenor_value = self._data[currency][horizon][sleeve]
        self.currency_var.set(currency)
        self.horizon_var.set(horizon)
        self.sleeve_var.set(sleeve)
        self.yield_var.set(f"{yield_value:.4f}")
        self.tenor_var.set(f"{tenor_value:.4f}")

    def get_data(self) -> dict[str, dict[str, dict[str, tuple[float, float]]]]:
        return deepcopy(self._data)
@dataclass
class TreeNode:
    allocation: Allocation
    children: list["TreeNode"]


@dataclass(slots=True)
class PlanRow:
    """Represents a single recommendation entry in the allocation plan."""

    allocation_id: int
    path: str
    currencies: tuple[str, ...]
    time_horizon: Optional[str]
    target_share: float
    current_value: float
    current_share: float
    target_value: float
    recommended_change: float
    share_diff: float
    action: str

    @property
    def currency(self) -> str:
        """Return the comma-separated currency label for persistence/display."""

        return ", ".join(code for code in self.currencies if code)


@dataclass(slots=True)
class CurrencyRiskResult:
    """Represents the optimised allocation slice for a single currency."""

    allocations: dict[tuple[str, str], float]
    by_bucket: dict[str, float]
    by_sleeve: dict[str, float]
    currency_share: float


def _format_amount(value: float) -> str:
    """Return a human friendly amount string."""

    return f"{value:,.2f}"


def _format_percent(value: float) -> str:
    """Return a percentage string with two decimals."""

    return f"{value:.2f}%"


def _format_share_delta(value: float) -> str:
    """Return a signed percentage point delta representation."""

    return f"{value:+.2f} pp"


class AllocationApp(ttk.Frame):
    """Main application frame that hosts the tree and the editor form."""

    def __init__(self, master: tk.Tk, repo: Optional[AllocationRepository] = None) -> None:
        super().__init__(master, padding=10)
        self.master.title("Money Allocation Manager")
        self.repo = repo or AllocationRepository()
        self.mode: str = "view"  # view | add | edit
        self.parent_for_new: Optional[int] = None
        self.selected_id: Optional[int] = None
        self.allocation_cache: Dict[int, Allocation] = {}

        self.name_var = tk.StringVar()
        self.currency_var = tk.StringVar()
        self.instrument_var = tk.StringVar()
        self.horizon_var = tk.StringVar()
        self.percent_var = tk.StringVar()
        self.value_var = tk.StringVar()
        self.include_var = tk.BooleanVar(value=True)
        self.path_var = tk.StringVar(value="No selection")
        self.child_sum_var = tk.StringVar(value="Children share: 0.00% of parent")
        self.status_var = tk.StringVar(value="Welcome! Use the buttons above to manage allocations.")

        self.grid(column=0, row=0, sticky="nsew")
        self.master.rowconfigure(0, weight=1)
        self.master.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self._create_menu()
        self.risk_library_defaults: dict[str, dict[str, dict[str, tuple[float, float]]]] = {}

        self._create_widgets()
        self.refresh_tree()

    # ------------------------------------------------------------------
    # UI construction helpers
    # ------------------------------------------------------------------
    def _create_menu(self) -> None:
        menubar = tk.Menu(self.master)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Import sample data", command=self._import_sample_data)
        file_menu.add_separator()
        file_menu.add_command(label="Import from CSV…", command=self._import_from_csv)
        file_menu.add_command(label="Export to CSV…", command=self._export_to_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.master.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        self.master.config(menu=menubar)

    def _create_widgets(self) -> None:
        # Toolbar with common actions
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(tuple(range(10)), weight=1)

        ttk.Button(toolbar, text="Add root", command=self._start_add_root).grid(row=0, column=0, padx=2)
        ttk.Button(toolbar, text="Add child", command=self._start_add_child).grid(row=0, column=1, padx=2)
        ttk.Button(toolbar, text="Edit", command=self._start_edit).grid(row=0, column=2, padx=2)
        self.save_button = ttk.Button(toolbar, text="Save", command=self._save_allocation, state="disabled")
        self.save_button.grid(row=0, column=3, padx=2)
        self.cancel_button = ttk.Button(toolbar, text="Cancel", command=self._cancel_edit, state="disabled")
        self.cancel_button.grid(row=0, column=4, padx=2)
        ttk.Button(toolbar, text="Delete", command=self._delete_allocation).grid(row=0, column=5, padx=2)
        ttk.Button(toolbar, text="Expand all", command=lambda: self._expand_collapse(True)).grid(row=0, column=6, padx=2)
        ttk.Button(toolbar, text="Collapse all", command=lambda: self._expand_collapse(False)).grid(row=0, column=7, padx=2)

        self.main_notebook = ttk.Notebook(self)
        self.main_notebook.grid(row=1, column=0, sticky="nsew")

        allocation_tab = ttk.Frame(self.main_notebook)
        allocation_tab.columnconfigure(0, weight=3)
        allocation_tab.columnconfigure(1, weight=2)
        allocation_tab.rowconfigure(0, weight=1)
        self.main_notebook.add(allocation_tab, text="Allocations")

        tree_frame = ttk.Frame(allocation_tab)
        tree_frame.grid(row=0, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        columns = ("currency", "target", "cumulative", "included", "horizon")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Allocation")
        self.tree.heading("currency", text="Currency")
        self.tree.heading("target", text="Share of parent")
        self.tree.heading("cumulative", text="Share of total")
        self.tree.heading("included", text="Included")
        self.tree.heading("horizon", text="Time horizon")
        self.tree.column("#0", width=240)
        self.tree.column("currency", width=80, anchor="center")
        self.tree.column("target", width=120, anchor="e")
        self.tree.column("cumulative", width=120, anchor="e")
        self.tree.column("included", width=80, anchor="center")
        self.tree.column("horizon", width=120, anchor="center")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.grid(row=0, column=0, sticky="nsew")

        tree_scroll_y = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")

        form = ttk.LabelFrame(allocation_tab, text="Allocation details")
        form.grid(row=0, column=1, padx=(10, 0), sticky="nsew")
        form.columnconfigure(1, weight=1)
        form.rowconfigure(8, weight=1)

        ttk.Label(form, text="Path:").grid(row=0, column=0, sticky="w")
        ttk.Label(form, textvariable=self.path_var, wraplength=260).grid(row=0, column=1, sticky="w")

        ttk.Label(form, text="Name:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.name_entry = ttk.Entry(form, textvariable=self.name_var, width=30)
        self.name_entry.grid(row=1, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(form, text="Currency:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.currency_entry = ttk.Entry(form, textvariable=self.currency_var)
        self.currency_entry.grid(row=2, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(form, text="Instrument:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.instrument_entry = ttk.Entry(form, textvariable=self.instrument_var)
        self.instrument_entry.grid(row=3, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(form, text="Time horizon:").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.horizon_combo = ttk.Combobox(
            form,
            textvariable=self.horizon_var,
            values=list(DEFAULT_TIME_HORIZONS),
            width=27,
        )
        self.horizon_combo.grid(row=4, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(form, text="Share of parent (%):").grid(row=5, column=0, sticky="w", pady=(6, 0))
        self.percent_entry = ttk.Entry(form, textvariable=self.percent_var)
        self.percent_entry.grid(row=5, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(form, text="Current value:").grid(row=6, column=0, sticky="w", pady=(6, 0))
        self.value_entry = ttk.Entry(form, textvariable=self.value_var)
        self.value_entry.grid(row=6, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(form, text="Included in roll-up:").grid(row=7, column=0, sticky="w", pady=(6, 0))
        self.include_check = ttk.Checkbutton(form, variable=self.include_var, text="Yes")
        self.include_check.grid(row=7, column=1, sticky="w", pady=(6, 0))

        ttk.Label(form, text="Notes:").grid(row=8, column=0, sticky="nw", pady=(6, 0))
        self.notes_text = tk.Text(form, height=8, wrap="word")
        self.notes_text.grid(row=8, column=1, sticky="nsew", pady=(6, 0))
        notes_scroll = ttk.Scrollbar(form, orient="vertical", command=self.notes_text.yview)
        self.notes_text.configure(yscrollcommand=notes_scroll.set)
        notes_scroll.grid(row=8, column=2, sticky="nsw")

        ttk.Label(form, textvariable=self.child_sum_var).grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))

        distribution_tab = ttk.Frame(self.main_notebook)
        distribution_tab.rowconfigure(0, weight=1)
        distribution_tab.columnconfigure(0, weight=1)
        self.distribution_tab = distribution_tab
        self.distribution_panel = DistributionPanel(
            distribution_tab,
            self.repo,
            self._on_distribution_saved,
            default_risk_inputs=self.risk_library_defaults,
        )
        self.distribution_panel.grid(row=0, column=0, sticky="nsew")
        self.main_notebook.add(distribution_tab, text="Distribute funds")

        risk_tab = RiskInputLibraryTab(
            self.main_notebook,
            on_changed=self._on_risk_library_changed,
            initial=self.risk_library_defaults,
        )
        self.risk_library_tab = risk_tab
        self.main_notebook.add(risk_tab, text="Risk input library")

        history_tab = ttk.Frame(self.main_notebook)
        history_tab.rowconfigure(0, weight=1)
        history_tab.columnconfigure(0, weight=1)
        self.history_tab = history_tab
        self.history_panel = DistributionHistoryPanel(history_tab, self.repo, self._on_distribution_deleted)
        self.history_panel.grid(row=0, column=0, sticky="nsew")
        self.main_notebook.add(history_tab, text="Distribution history")

        status = ttk.Label(self, textvariable=self.status_var, anchor="w")
        status.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        self._set_form_state(False)

    def _on_risk_library_changed(
        self, data: dict[str, dict[str, dict[str, tuple[float, float]]]]
    ) -> None:
        self.risk_library_defaults = data
        self.distribution_panel.update_default_risk_inputs(data)
    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------
    def _import_sample_data(self) -> None:
        if not messagebox.askyesno(
            "Replace data",
            "This will load a curated sample dataset. Existing allocations will be removed. Continue?",
        ):
            return
        populate_with_sample_data(self.repo, replace=True)
        self.refresh_tree()
        self.status_var.set("Sample data imported successfully.")

    def _import_from_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Import allocations from CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Replace data",
            "Importing from CSV will replace all existing allocations. Continue?",
        ):
            return
        try:
            allocations: list[Allocation] = []
            with open(path, "r", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                required = {
                    "id",
                    "parent_id",
                    "name",
                    "currency",
                    "instrument",
                    "target_percent",
                    "include_in_rollup",
                    "current_value",
                    "notes",
                    "sort_order",
                }
                if not required.issubset(reader.fieldnames or []):
                    missing = required.difference(reader.fieldnames or [])
                    raise ValueError(f"Missing columns in CSV: {', '.join(sorted(missing))}")
                for row in reader:
                    name = row["name"].strip()
                    if not name:
                        continue
                    try:
                        time_horizon = canonicalize_time_horizon(row.get("time_horizon"))
                    except ValueError as exc:
                        raise ValueError(
                            "Time horizon must follow the '<number><unit>' pattern (e.g. 1Y, 3M, 6W or 10D) "
                            f"for allocation '{name}'."
                        ) from exc
                    allocations.append(
                        Allocation(
                            id=int(row["id"]) if row["id"].strip() else None,
                            parent_id=int(row["parent_id"]) if row["parent_id"].strip() else None,
                            name=name,
                            currency=row["currency"].strip() or None,
                            instrument=row["instrument"].strip() or None,
                            time_horizon=time_horizon,
                            target_percent=float(row["target_percent"] or 0.0),
                            include_in_rollup=row["include_in_rollup"].strip().lower() in {"1", "true", "yes"},
                            current_value=float(row["current_value"] or 0.0),
                            notes=row["notes"],
                            sort_order=int(row["sort_order"] or 0),
                        )
                    )
            self.repo.clear_all()
            # When ids are provided we insert them directly to preserve hierarchy order.
            self.repo.bulk_insert(allocations)
        except Exception as exc:  # noqa: BLE001 - show the error to the user
            messagebox.showerror("Import failed", f"Could not import data: {exc}")
            return
        self.refresh_tree()
        self.status_var.set(f"Imported {len(allocations)} allocations from CSV.")

    def _export_to_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Export allocations to CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        allocations = self.repo.get_all_allocations()
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(
                    [
                        "id",
                        "parent_id",
                        "name",
                        "currency",
                        "instrument",
                        "time_horizon",
                        "target_percent",
                        "include_in_rollup",
                        "current_value",
                        "notes",
                        "sort_order",
                    ]
                )
                for allocation in allocations:
                    writer.writerow(
                        [
                            allocation.id,
                            allocation.parent_id if allocation.parent_id is not None else "",
                            allocation.name,
                            allocation.currency or "",
                            allocation.instrument or "",
                            allocation.normalized_time_horizon,
                            f"{allocation.target_percent:.4f}",
                            int(allocation.include_in_rollup),
                            f"{allocation.current_value:.2f}",
                            allocation.notes,
                            allocation.sort_order,
                        ]
                    )
        except OSError as exc:  # pragma: no cover - we simply report errors
            messagebox.showerror("Export failed", f"Could not write file: {exc}")
            return
        self.status_var.set(f"Exported {len(allocations)} allocations to {Path(path).name}.")

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------
    def _start_add_root(self) -> None:
        self.parent_for_new = None
        self._begin_edit_mode("add", "Adding a new top-level allocation")

    def _start_add_child(self) -> None:
        if not self.selected_id:
            messagebox.showinfo("Select a node", "Select a parent allocation in the tree first.")
            return
        self.parent_for_new = self.selected_id
        parent_path = self._get_path(self.parent_for_new)
        self._begin_edit_mode("add", f"Adding a new child under {parent_path}")

    def _start_edit(self) -> None:
        if not self.selected_id:
            messagebox.showinfo("Select a node", "Choose an allocation to edit from the tree.")
            return
        self.parent_for_new = None
        self._begin_edit_mode("edit", "Editing existing allocation")

    def _begin_edit_mode(self, mode: str, status_message: str) -> None:
        self.mode = mode
        if mode == "add":
            self.selected_id = None
            self._clear_form()
            parent_path = (
                "Top level" if self.parent_for_new is None else self._get_path(self.parent_for_new)
            )
            self.path_var.set(parent_path)
        elif mode == "edit":
            if not self.tree.selection():
                return
            current_id = int(self.tree.selection()[0])
            allocation = self.allocation_cache.get(current_id)
            if not allocation:
                return
            self.selected_id = current_id
            self._fill_form(allocation)
            self.path_var.set(self._get_path(current_id))
        self._set_form_state(True)
        self.save_button.config(text="Create" if mode == "add" else "Save", state="normal")
        self.cancel_button.config(state="normal")
        self.status_var.set(status_message)

    def _cancel_edit(self) -> None:
        self.mode = "view"
        self.parent_for_new = None
        self.save_button.config(state="disabled", text="Save")
        self.cancel_button.config(state="disabled")
        self._set_form_state(False)
        if self.selected_id:
            allocation = self.allocation_cache.get(self.selected_id)
            if allocation:
                self._fill_form(allocation)
                self.path_var.set(self._get_path(self.selected_id))
        else:
            self._clear_form()
            self.path_var.set("No selection")
        self.status_var.set("Edit cancelled.")

    def _save_allocation(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Missing name", "Please provide a name for the allocation.")
            return

        percent_text = self.percent_var.get().strip()
        if not percent_text:
            percent_value = 0.0
        else:
            try:
                percent_value = float(percent_text)
            except ValueError:
                messagebox.showerror("Invalid percentage", "Share of parent must be a number.")
                return

        value_text = self.value_var.get().strip()
        if not value_text:
            current_value = 0.0
        else:
            try:
                current_value = float(value_text)
            except ValueError:
                messagebox.showerror("Invalid value", "Current value must be a number.")
                return

        notes = self.notes_text.get("1.0", "end").strip()
        currency = self.currency_var.get().strip() or None
        instrument = self.instrument_var.get().strip() or None
        try:
            horizon = canonicalize_time_horizon(self.horizon_var.get())
        except ValueError:
            messagebox.showerror(
                "Invalid time horizon",
                "Time horizon must be a positive integer followed by Y, M, W or D "
                "(for example 1Y, 3M, 6W or 10D).",
            )
            return
        self.horizon_var.set(horizon or "")
        include = bool(self.include_var.get())

        if self.mode == "add":
            parent_id = self.parent_for_new
            sort_order = self.repo.get_next_sort_order(parent_id)
            allocation = Allocation(
                id=None,
                parent_id=parent_id,
                name=name,
                currency=currency,
                instrument=instrument,
                time_horizon=horizon,
                target_percent=percent_value,
                include_in_rollup=include,
                notes=notes,
                sort_order=sort_order,
                current_value=current_value,
            )
            new_id = self.repo.add_allocation(allocation)
            self.status_var.set(f"Created allocation '{name}'.")
            self.mode = "view"
            self.parent_for_new = None
            self._set_form_state(False)
            self.save_button.config(state="disabled", text="Save")
            self.cancel_button.config(state="disabled")
            self.refresh_tree(select_id=new_id)
            return

        if self.mode == "edit":
            if not self.selected_id:
                return
            current = self.repo.get_allocation(self.selected_id)
            if not current:
                messagebox.showerror("Missing allocation", "The selected allocation no longer exists.")
                self.refresh_tree()
                return
            current.name = name
            current.currency = currency
            current.instrument = instrument
            current.time_horizon = horizon
            current.target_percent = percent_value
            current.include_in_rollup = include
            current.notes = notes
            current.current_value = current_value
            self.repo.update_allocation(current)
            self.status_var.set(f"Updated allocation '{name}'.")
            self.mode = "view"
            self._set_form_state(False)
            self.save_button.config(state="disabled", text="Save")
            self.cancel_button.config(state="disabled")
            self.refresh_tree(select_id=current.id)
            return

    def _delete_allocation(self) -> None:
        if not self.tree.selection():
            messagebox.showinfo("Select a node", "Choose an allocation to delete first.")
            return
        allocation_id = int(self.tree.selection()[0])
        allocation = self.allocation_cache.get(allocation_id)
        if not allocation:
            return
        if not messagebox.askyesno(
            "Delete allocation",
            f"Delete '{allocation.name}' and all of its descendants? This action cannot be undone.",
        ):
            return
        self.repo.delete_allocation(allocation_id)
        self.status_var.set(f"Deleted allocation '{allocation.name}'.")
        self.mode = "view"
        self.parent_for_new = None
        self.selected_id = None
        self._set_form_state(False)
        self.save_button.config(state="disabled", text="Save")
        self.cancel_button.config(state="disabled")
        self.refresh_tree()

    def _expand_collapse(self, expand: bool) -> None:
        for item in self.tree.get_children(""):
            self._expand_recursive(item, expand)

    def _expand_recursive(self, item: str, expand: bool) -> None:
        self.tree.item(item, open=expand)
        for child in self.tree.get_children(item):
            self._expand_recursive(child, expand)

    # ------------------------------------------------------------------
    # Distribution helpers
    # ------------------------------------------------------------------
    def _on_distribution_saved(self, name: str, count: int) -> None:
        self.status_var.set(
            f"Saved distribution '{name}' with {count} recommendation{'s' if count != 1 else ''}."
        )
        self.history_panel.refresh()

    def _on_distribution_deleted(self, name: str) -> None:
        self.status_var.set(f"Deleted distribution '{name}'.")
        self.history_panel.refresh()

    # ------------------------------------------------------------------
    # Tree interactions
    # ------------------------------------------------------------------
    def refresh_tree(self, *, select_id: Optional[int] = None) -> None:
        self.tree.delete(*self.tree.get_children())
        allocations = self.repo.get_all_allocations()
        self.allocation_cache = {allocation.id: allocation for allocation in allocations}

        unique_horizons = sorted(
            {allocation.normalized_time_horizon for allocation in allocations if allocation.normalized_time_horizon}
        )
        combined_horizons = list(dict.fromkeys((*DEFAULT_TIME_HORIZONS, *unique_horizons)))
        self.horizon_combo.configure(values=combined_horizons)

        nodes: Dict[int, TreeNode] = {}
        roots: list[TreeNode] = []
        for allocation in allocations:
            nodes[allocation.id] = TreeNode(allocation=allocation, children=[])
        for allocation in allocations:
            node = nodes[allocation.id]
            if allocation.parent_id is None or allocation.parent_id not in nodes:
                roots.append(node)
            else:
                nodes[allocation.parent_id].children.append(node)

        def sort_children(items: Iterable[TreeNode]) -> None:
            for node in items:
                node.children.sort(key=lambda c: (c.allocation.sort_order, c.allocation.id or 0))
                sort_children(node.children)

        sort_children(roots)
        roots.sort(key=lambda n: (n.allocation.sort_order, n.allocation.id or 0))

        for node in roots:
            self._insert_node("", node, parent_share=100.0)

        if select_id is not None:
            iid = str(select_id)
            if iid in self.tree.get_children("") or self.tree.exists(iid):
                self.tree.selection_set(iid)
                self.tree.focus(iid)
                self.tree.see(iid)
                self.selected_id = select_id
        elif self.tree.get_children(""):
            first = self.tree.get_children("")[0]
            self.tree.selection_set(first)
            self.tree.focus(first)
            self.selected_id = int(first)
        else:
            self.selected_id = None
            self._clear_form()
            self.path_var.set("No selection")
            self.child_sum_var.set("Children share: 0.00% of parent")

        if self.selected_id:
            allocation = self.allocation_cache.get(self.selected_id)
            if allocation:
                self._fill_form(allocation)
                self.path_var.set(self._get_path(self.selected_id))
                self._update_children_summary(self.selected_id)

    def _insert_node(self, parent: str, node: TreeNode, parent_share: float) -> None:
        allocation = node.allocation
        own_share = allocation.target_percent
        cumulative = parent_share * (own_share / 100.0)
        iid = str(allocation.id)
        self.tree.insert(
            parent,
            "end",
            iid=iid,
            text=allocation.name,
            values=(
                allocation.normalized_currency,
                f"{own_share:.2f}%",
                f"{cumulative:.2f}%",
                "Yes" if allocation.include_in_rollup else "No",
                allocation.normalized_time_horizon,
            ),
            open=True,
        )
        next_parent_share = cumulative
        for child in node.children:
            self._insert_node(iid, child, next_parent_share)

    def _on_tree_select(self, event: tk.Event[tk.EventType]) -> None:  # pragma: no cover - UI callback
        if not self.tree.selection():
            return
        iid = int(self.tree.selection()[0])
        self.selected_id = iid
        allocation = self.allocation_cache.get(iid)
        if allocation:
            self._fill_form(allocation)
            self.path_var.set(self._get_path(iid))
            self._update_children_summary(iid)
        if self.mode != "view":
            self._cancel_edit()

    # ------------------------------------------------------------------
    # Form helpers
    # ------------------------------------------------------------------
    def _set_form_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for entry in (
            self.name_entry,
            self.currency_entry,
            self.instrument_entry,
            self.percent_entry,
            self.value_entry,
        ):
            entry.config(state=state)
        self.horizon_combo.config(state=state)
        self.include_check.config(state=state)
        if enabled:
            self.notes_text.config(state="normal")
        else:
            self.notes_text.config(state="disabled")

    def _clear_form(self) -> None:
        self.name_var.set("")
        self.currency_var.set("")
        self.instrument_var.set("")
        self.horizon_var.set("")
        self.percent_var.set("0")
        self.value_var.set("0")
        self.include_var.set(True)
        self.notes_text.config(state="normal")
        self.notes_text.delete("1.0", "end")
        self.notes_text.config(state="disabled")

    def _fill_form(self, allocation: Allocation) -> None:
        self.name_var.set(allocation.name)
        self.currency_var.set(allocation.normalized_currency)
        self.instrument_var.set(allocation.normalized_instrument)
        self.horizon_var.set(allocation.normalized_time_horizon)
        self.percent_var.set(f"{allocation.target_percent:.2f}")
        self.value_var.set(f"{allocation.current_value:.2f}")
        self.include_var.set(allocation.include_in_rollup)
        self.notes_text.config(state="normal")
        self.notes_text.delete("1.0", "end")
        if allocation.notes:
            self.notes_text.insert("1.0", allocation.notes)
        self.notes_text.config(state="disabled")

    def _update_children_summary(self, allocation_id: int) -> None:
        children = self.repo.get_children(allocation_id)
        total = sum(child.target_percent for child in children)
        self.child_sum_var.set(f"Children share: {total:.2f}% of parent")

    def _get_path(self, allocation_id: Optional[int]) -> str:
        if allocation_id is None:
            return ""
        parts: list[str] = []
        current_id = allocation_id
        visited = set()
        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            allocation = self.allocation_cache.get(current_id)
            if not allocation:
                break
            parts.append(allocation.name)
            current_id = allocation.parent_id if isinstance(allocation.parent_id, int) else None
        return " > ".join(reversed(parts)) if parts else ""


class DistributionPanel(ttk.Frame):
    """Inline panel that calculates and persists distribution recommendations."""

    def __init__(
        self,
        master: tk.Misc,
        repo: AllocationRepository,
        on_saved: Callable[[str, int], None],
        *,
        default_risk_inputs: Optional[dict[str, dict[str, dict[str, tuple[float, float]]]]] = None,
    ) -> None:
        super().__init__(master, padding=10)
        self.repo = repo
        self.on_saved = on_saved
        self.plan_rows: list[PlanRow] = []
        self.plan_rows_by_currency: dict[str, list[PlanRow]] = {}
        self.currency_totals: dict[str, dict[str, float]] = {}
        self.amount: float = 0.0
        self.tolerance: float = 0.0
        self.totals: dict[str, float] = {
            "current_total": 0.0,
            "target_total": 0.0,
            "invest_total": 0.0,
            "divest_total": 0.0,
        }
        self.selected_currencies: Optional[list[str]] = None
        self._manual_defaults: dict[str, dict[str, dict[str, tuple[float, float]]]] = deepcopy(
            default_risk_inputs or {}
        )
        self._risk_inputs: dict[str, dict[str, dict[str, tuple[float, float]]]] = deepcopy(
            self._manual_defaults
        )
        self._risk_selection_details: dict[
            tuple[str, str, str], tuple[Optional[float], Optional[float]]
        ] = {}
        self.risk_summary_lines: dict[str, list[str]] = {}
        self.risk_results: dict[str, CurrencyRiskResult] = {}
        self.currency_trees: dict[str, ttk.Treeview] = {}
        self.currency_frames: dict[str, ttk.Frame] = {}
        self._last_horizon_requirements: dict[str, list[str]] = {}

        self.amount_var = tk.StringVar(value="0")
        self.tolerance_var = tk.StringVar(value="2.0")
        self.currency_filter_var = tk.StringVar()
        self.time_horizon_choices = self._build_time_horizon_choices()
        default_horizon = (
            self.time_horizon_choices[0]
            if self.time_horizon_choices
            else ALL_TIME_HORIZONS_OPTION
        )
        self.time_horizon_var = tk.StringVar(value=default_horizon)
        self.selected_time_horizon_label = default_horizon
        self.summary_var = tk.StringVar(value="Enter an amount and press Calculate.")

        self.distribution_name_var = tk.StringVar()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        form = ttk.Frame(container)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(4, weight=1)

        ttk.Label(form, text="Amount to distribute:").grid(row=0, column=0, sticky="w")
        self.amount_entry = ttk.Entry(form, textvariable=self.amount_var, width=18)
        self.amount_entry.grid(row=0, column=1, sticky="w", padx=(4, 12))

        ttk.Label(form, text="Tolerance (pp):").grid(row=0, column=2, sticky="w")
        ttk.Entry(form, textvariable=self.tolerance_var, width=10).grid(
            row=0, column=3, sticky="w", padx=(4, 12)
        )

        ttk.Button(form, text="Calculate", command=self._calculate_plan).grid(
            row=0, column=4, sticky="e"
        )

        ttk.Label(form, text="Currencies (comma-separated):").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        ttk.Entry(
            form,
            textvariable=self.currency_filter_var,
            width=24,
        ).grid(row=1, column=1, sticky="w", padx=(4, 12), pady=(6, 0))

        ttk.Label(form, text="Time horizon:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.horizon_filter_combo = ttk.Combobox(
            form,
            textvariable=self.time_horizon_var,
            values=self.time_horizon_choices,
            state="readonly",
            width=18,
        )
        self.horizon_filter_combo.grid(
            row=2, column=1, sticky="w", padx=(4, 12), pady=(6, 0)
        )

        tree_frame = ttk.Frame(container)
        tree_frame.pack(fill="both", expand=True, pady=(10, 0))
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self.plan_notebook = ttk.Notebook(tree_frame)
        self.plan_notebook.grid(row=0, column=0, sticky="nsew")
        self.risk_editor = RiskInputEditor(container)
        self.risk_editor.hide()
        self._show_empty_state("Enter an amount and press Calculate.")

        self.summary_label = ttk.Label(
            container,
            textvariable=self.summary_var,
            anchor="w",
            justify="left",
            wraplength=720,
        )
        self.summary_label.pack(fill="x", pady=(10, 0))
        self.risk_editor.configure_pack(before=self.summary_label)

        button_row = ttk.Frame(container)
        button_row.pack(fill="x", pady=(10, 0))
        ttk.Label(button_row, text="Distribution name:").pack(side="left")
        ttk.Entry(button_row, textvariable=self.distribution_name_var, width=36).pack(
            side="left", padx=(6, 12)
        )
        self.save_button = ttk.Button(
            button_row,
            text="Save distribution",
            command=self._save_distribution,
            state="disabled",
        )
        self.save_button.pack(side="left")

        self.amount_entry.focus_set()

    def focus_amount_entry(self) -> None:
        self.amount_entry.focus_set()

    def _clear_plan_views(self) -> None:
        for child in list(self.plan_notebook.winfo_children()):
            child.destroy()
        self.currency_trees.clear()
        self.currency_frames.clear()

    def _show_empty_state(self, message: str) -> None:
        self._clear_plan_views()
        self.risk_editor.clear()
        self.risk_editor.hide()
        self._last_horizon_requirements = {}
        frame = ttk.Frame(self.plan_notebook, padding=20)
        ttk.Label(
            frame,
            text=message,
            justify="center",
            wraplength=640,
        ).pack(expand=True, fill="both")
        self.plan_notebook.add(frame, text="Overview")
        self.plan_notebook.select(frame)
        self.summary_var.set(message)

    def _ensure_currency_tree(self, currency: str) -> ttk.Treeview:
        if currency in self.currency_trees:
            tree = self.currency_trees[currency]
            tree.delete(*tree.get_children())
            return tree

        frame = ttk.Frame(self.plan_notebook)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        columns = ("amount", "notes")
        tree = ttk.Treeview(frame, columns=columns, show="tree headings", height=15)
        tree.heading("#0", text="Allocation")
        tree.column("#0", width=320, anchor="w")
        tree.heading("amount", text="Amount")
        tree.column("amount", width=140, anchor="e")
        tree.heading("notes", text="Details")
        tree.column("notes", width=260, anchor="w")

        tree_scroll_y = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree_scroll_x = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")

        display_label = self._display_currency(currency)
        self.plan_notebook.add(frame, text=display_label)
        self.currency_trees[currency] = tree
        self.currency_frames[currency] = frame
        return tree

    @staticmethod
    def _display_currency(currency: str) -> str:
        return currency or "Unspecified"

    def _parse_currency_filters(self) -> Optional[list[str]]:
        raw = self.currency_filter_var.get()
        if not raw:
            return None
        seen: dict[str, None] = {}
        for part in raw.split(","):
            text = part.strip()
            if not text:
                continue
            upper = text.upper()
            key = "" if upper in _UNSPECIFIED_CURRENCY_ALIASES else upper
            seen.setdefault(key, None)
        return list(seen.keys()) or None

    @staticmethod
    def _parse_currency_codes(raw: Optional[str]) -> tuple[str, ...]:
        text = (raw or "").strip()
        if not text:
            return ("",)

        seen: dict[str, None] = {}
        for part in text.split(","):
            piece = part.strip()
            if not piece:
                continue
            upper = piece.upper()
            key = "" if upper in _UNSPECIFIED_CURRENCY_ALIASES else upper
            seen.setdefault(key, None)

        if not seen:
            return ("",)

        return tuple(seen.keys())

    def _update_summary(self) -> None:
        if not self.plan_rows:
            return

        overall_invest = max(self.totals.get("invest_total", 0.0), 0.0)
        overall_divest = abs(self.totals.get("divest_total", 0.0))
        lines = [
            f"Current total: {_format_amount(self.totals.get('current_total', 0.0))}",
            f"Target total: {_format_amount(self.totals.get('target_total', 0.0))} (deposit {_format_amount(self.amount)})",
            f"Invest: {_format_amount(overall_invest)} | Divest: {_format_amount(overall_divest)}",
        ]

        if self.selected_time_horizon_label:
            lines.append(f"Time horizon: {self.selected_time_horizon_label}")

        if self.selected_currencies:
            display_names = ", ".join(
                self._display_currency(value) for value in self.selected_currencies
            )
            lines.append(f"Currencies: {display_names}")
        else:
            lines.append("Currencies: All")

        overall_risk_lines = self.risk_summary_lines.get("__overall__")
        if overall_risk_lines:
            lines.append("")
            lines.extend(overall_risk_lines)

        for currency in sorted(self.currency_totals):
            totals = self.currency_totals[currency]
            lines.append("")
            lines.append(f"{self._display_currency(currency)}:")
            lines.append(
                "  Current "
                + _format_amount(totals.get("current_total", 0.0))
                + " → Target "
                + _format_amount(totals.get("target_total", 0.0))
            )
            lines.append(
                "  Invest "
                + _format_amount(max(totals.get("invest_total", 0.0), 0.0))
                + " | Divest "
                + _format_amount(abs(totals.get("divest_total", 0.0)))
            )
            risk_lines = self.risk_summary_lines.get(currency, [])
            if risk_lines:
                lines.append("")
                lines.extend(f"  {text}" for text in risk_lines)

        self.summary_var.set("\n".join(lines))

    def _build_time_horizon_choices(self) -> list[str]:
        allocations = self.repo.get_all_allocations()
        unique_horizons = sorted(
            {allocation.normalized_time_horizon for allocation in allocations if allocation.normalized_time_horizon}
        )
        combined = list(dict.fromkeys((*DEFAULT_TIME_HORIZONS, *unique_horizons)))
        if combined:
            return [ALL_TIME_HORIZONS_OPTION, *combined]
        return [ALL_TIME_HORIZONS_OPTION]

    # ------------------------------------------------------------------
    # Plan calculation
    # ------------------------------------------------------------------

    def _calculate_plan(self) -> None:
        self.risk_summary_lines = {}
        self.risk_results = {}
        self._risk_selection_details = {}
        self.plan_rows_by_currency = {}
        try:
            amount = float(self.amount_var.get())
        except ValueError:
            messagebox.showerror("Invalid amount", "The amount to distribute must be a number.", parent=self)
            return
        if amount < 0:
            messagebox.showerror(
                "Invalid amount",
                "The amount to distribute cannot be negative.",
                parent=self,
            )
            return

        try:
            tolerance = float(self.tolerance_var.get())
        except ValueError:
            messagebox.showerror(
                "Invalid tolerance", "The tolerance must be expressed as a number.", parent=self
            )
            return
        if tolerance < 0:
            messagebox.showerror(
                "Invalid tolerance", "Tolerance cannot be negative.", parent=self
            )
            return

        selected_label = self.time_horizon_var.get().strip()
        if not selected_label or selected_label == ALL_TIME_HORIZONS_OPTION:
            horizon_filter = None
            display_label = ALL_TIME_HORIZONS_OPTION
            self.time_horizon_var.set(display_label)
        else:
            try:
                canonical_label = canonicalize_time_horizon(selected_label)
            except ValueError:
                canonical_label = selected_label
            horizon_filter = canonical_label
            display_label = canonical_label
            self.time_horizon_var.set(display_label)
        self.selected_time_horizon_label = display_label
        currency_filters = self._parse_currency_filters()
        self.selected_currencies = currency_filters[:] if currency_filters else None
        plan_rows, totals, currency_totals = self._build_plan(
            amount,
            tolerance,
            horizon_filter,
            set(currency_filters) if currency_filters else None,
        )
        if not plan_rows:
            if currency_filters and horizon_filter is not None:
                title = "No matching allocations"
                message = (
                    "No allocations match the selected currencies and time horizon. "
                    "Adjust the filters or update your allocation settings and try again."
                )
            elif currency_filters:
                title = "No matching currencies"
                message = (
                    "No allocations match the selected currencies. Adjust the filter or "
                    "update the allocation currencies and try again."
                )
            elif horizon_filter is not None:
                title = "No matching allocations"
                message = (
                    "No allocations match the selected time horizon. Adjust the filter or "
                    "update the allocation horizons and try again."
                )
            else:
                title = "No included allocations"
                message = (
                    "None of the allocations are marked as included in the roll-up, therefore "
                    "no distribution recommendations can be produced."
                )
            messagebox.showinfo(title, message, parent=self)
            self.plan_rows = []
            self.currency_totals = {}
            self.totals = {
                "current_total": 0.0,
                "target_total": 0.0,
                "invest_total": 0.0,
                "divest_total": 0.0,
            }
            self.distribution_name_var.set("")
            self._show_empty_state("No plan available. Update your allocations and try again.")
            self.save_button.config(state="disabled")
            return

        self.plan_rows = plan_rows
        self.plan_rows_by_currency = {}
        for row in plan_rows:
            codes = row.currencies if row.currencies else ("",)
            for code in codes:
                self.plan_rows_by_currency.setdefault(code, []).append(row)
        self.amount = amount
        self.tolerance = tolerance
        self.totals = totals
        self.currency_totals = currency_totals
        if not self.distribution_name_var.get().strip():
            default_name = datetime.now().strftime("Distribution %Y-%m-%d %H:%M")
            self.distribution_name_var.set(default_name)
        risk_lines, risk_results = self._build_risk_summary(self.plan_rows_by_currency)
        self.risk_summary_lines = risk_lines
        self.risk_results = risk_results
        self._populate_plan_views()
        self._update_summary()
        self.save_button.config(state="normal")

    def _populate_plan_views(self) -> None:
        if not self.plan_rows_by_currency:
            self._show_empty_state("No plan available. Update your allocations and try again.")
            return

        self._clear_plan_views()
        sleeve_labels = {
            "rates": "Government (DV01)",
            "tips": "Inflation (BE01)",
            "credit": "Credit (CS01)",
        }

        overall_invest_total = max(self.totals.get("invest_total", 0.0), 0.0)

        for currency in sorted(self.plan_rows_by_currency):
            tree = self._ensure_currency_tree(currency)
            rows = self.plan_rows_by_currency[currency]
            risk_result = self.risk_results.get(currency)
            if risk_result and overall_invest_total > 0:
                for bucket, bucket_share in sorted(
                    risk_result.by_bucket.items(), key=lambda item: item[0]
                ):
                    bucket_amount = overall_invest_total * bucket_share
                    bucket_id = f"bucket::{bucket}"
                    tree.insert(
                        "",
                        "end",
                        iid=bucket_id,
                        text=bucket,
                        values=(
                            _format_amount(bucket_amount),
                            f"Share {bucket_share * 100:.2f}% of total",
                        ),
                    )
                    for sleeve in ("rates", "tips", "credit"):
                        allocation_share = risk_result.allocations.get((bucket, sleeve), 0.0)
                        if allocation_share <= 0:
                            continue
                        amount_value = overall_invest_total * allocation_share
                        selection = self._risk_selection_details.get((currency, bucket, sleeve))
                        notes = [f"Share {allocation_share * 100:.2f}% of total"]
                        if selection:
                            yield_value, tenor_value = selection
                            if yield_value is not None:
                                notes.append(f"Yield {yield_value:.2f}%")
                            if tenor_value is not None:
                                notes.append(f"Tenor {tenor_value:.2f}y")
                        notes_text = " | ".join(notes)
                        tree.insert(
                            bucket_id,
                            "end",
                            text=sleeve_labels.get(sleeve, sleeve.capitalize()),
                            values=(
                                _format_amount(amount_value),
                                notes_text,
                            ),
                        )
            else:
                for row in rows:
                    notes = (
                        f"Current {_format_amount(row.current_value)} → Target {_format_amount(row.target_value)}"
                    )
                    action = row.action.split("(")[0].strip()
                    if action:
                        notes = f"{action}: {notes}"
                    tree.insert(
                        "",
                        "end",
                        iid=str(row.allocation_id),
                        text=row.path,
                        values=(
                            _format_amount(row.recommended_change),
                            notes,
                        ),
                    )

        tabs = self.plan_notebook.tabs()
        if tabs:
            self.plan_notebook.select(tabs[0])

    def _build_risk_summary(
        self, plan_rows_by_currency: dict[str, list[PlanRow]]
    ) -> tuple[dict[str, list[str]], dict[str, CurrencyRiskResult]]:
        horizon_map: dict[str, list[str]] = {}
        for currency, rows in plan_rows_by_currency.items():
            horizons = sorted({row.time_horizon for row in rows if row.time_horizon})
            if horizons:
                horizon_map[currency] = horizons
        if not horizon_map:
            self.risk_editor.clear()
            self.risk_editor.hide()
            return {}, {}

        self._last_horizon_requirements = {currency: list(horizons) for currency, horizons in horizon_map.items()}
        self.risk_editor.set_requirements(horizon_map, self._risk_inputs)
        try:
            input_results = self.risk_editor.collect()
        except ValueError as exc:
            message = str(exc)
            self.risk_editor.set_status(message)
            notice = {
                "__overall__": [
                    "Risk summary – all currencies (equal currency allocation enforced):",
                    f"  {message}",
                    "  Update the risk inputs section and calculate again.",
                ]
            }
            return notice, {}

        for currency, result in input_results.items():
            self._risk_inputs[currency] = result

        def make_bucket_key(currency: str, bucket: str) -> str:
            prefix = currency or "__"
            return f"{prefix}::{bucket}"

        def parse_bucket_key(value: str) -> tuple[str, str]:
            parts = value.split("::", 1)
            if len(parts) == 2:
                currency_part, bucket_part = parts
            else:  # pragma: no cover - defensive
                currency_part, bucket_part = "__", value
            currency_value = "" if currency_part == "__" else currency_part
            return currency_value, bucket_part

        self._risk_selection_details = {}
        inactive_currency_lines: dict[str, list[str]] = {}
        combined_bucket_weights: dict[str, float] = {}
        rates_yields: dict[str, Optional[float]] = {}
        tips_yields: dict[str, Optional[float]] = {}
        credit_yields: dict[str, Optional[float]] = {}
        durations: dict[tuple[str, str], float] = {}
        bucket_currency_map: dict[str, tuple[str, str]] = {}
        bucket_weights_by_currency: dict[str, dict[str, float]] = {}
        currency_totals: dict[str, float] = {}

        currencies = sorted(horizon_map, key=lambda value: value or "")
        if not currencies:
            return {}, {}

        sleeve_labels = {
            "rates": "Government (DV01)",
            "tips": "Inflation (BE01)",
            "credit": "Credit (CS01)",
        }

        for currency in currencies:
            rows = plan_rows_by_currency.get(currency, [])
            selections = input_results.get(currency)
            if not selections:
                inactive_currency_lines[currency] = [
                    f"Risk summary – {self._display_currency(currency)}:",
                    "  Skipped: no risk inputs were provided.",
                ]
                continue

            bucket_totals: dict[str, float] = {}
            for row in rows:
                if not row.time_horizon:
                    continue
                bucket_totals[row.time_horizon] = bucket_totals.get(row.time_horizon, 0.0) + row.target_share

            total_share = sum(bucket_totals.values())
            if math.isclose(total_share, 0.0, abs_tol=1e-9):
                inactive_currency_lines[currency] = [
                    f"Risk summary – {self._display_currency(currency)}:",
                    "  Skipped: no investable allocations with time horizons were found.",
                ]
                continue

            normalized_weights = {
                bucket: share / total_share
                for bucket, share in bucket_totals.items()
                if share > 0.0
            }
            if not normalized_weights:
                inactive_currency_lines[currency] = [
                    f"Risk summary – {self._display_currency(currency)}:",
                    "  Skipped: no positive allocation weights detected.",
                ]
                continue

            bucket_weights_by_currency[currency] = normalized_weights
            currency_totals[currency] = total_share
            for bucket in normalized_weights:
                combined_key = make_bucket_key(currency, bucket)
                bucket_currency_map[combined_key] = (currency, bucket)

            for bucket, sleeve_data in selections.items():
                combined_key = make_bucket_key(currency, bucket)
                if combined_key not in bucket_currency_map:
                    continue
                bucket_duration = horizon_to_years(bucket)
                for sleeve, (yield_value, tenor_value) in sleeve_data.items():
                    if yield_value is None:
                        continue
                    if sleeve == "rates":
                        rates_yields[combined_key] = yield_value
                    elif sleeve == "tips":
                        tips_yields[combined_key] = yield_value
                    elif sleeve == "credit":
                        credit_yields[combined_key] = yield_value
                    durations[(combined_key, sleeve)] = bucket_duration
                    tenor = tenor_value if tenor_value is not None else bucket_duration
                    self._risk_selection_details[(currency, bucket, sleeve)] = (yield_value, tenor)

        if not bucket_weights_by_currency:
            return inactive_currency_lines, {}

        investable_total = sum(currency_totals.values())
        if math.isclose(investable_total, 0.0, abs_tol=1e-9):
            return inactive_currency_lines, {}

        for currency, bucket_weights in bucket_weights_by_currency.items():
            currency_share = currency_totals[currency] / investable_total
            for bucket, weight in bucket_weights.items():
                combined_key = make_bucket_key(currency, bucket)
                combined_bucket_weights[combined_key] = weight * currency_share * 100.0

        spec = ProblemSpec(
            bucket_weights=combined_bucket_weights,
            rates_yields=rates_yields,
            tips_yields=tips_yields,
            credit_yields=credit_yields,
            durations=durations,
        )

        try:
            optimisation = run_risk_equal_optimization(spec)
        except (RuntimeError, ValueError) as exc:
            overall_lines = [
                "Risk summary – all currencies (equal currency allocation enforced):",
                f"  {exc}",
            ]
            inactive_currency_lines["__overall__"] = overall_lines
            return inactive_currency_lines, {}

        results_map: dict[str, CurrencyRiskResult] = {}

        def ensure_currency_entry(currency: str) -> CurrencyRiskResult:
            entry = results_map.get(currency)
            if entry is None:
                entry = CurrencyRiskResult(
                    allocations={},
                    by_bucket={},
                    by_sleeve={"rates": 0.0, "tips": 0.0, "credit": 0.0},
                    currency_share=0.0,
                )
                results_map[currency] = entry
            return entry

        for bucket_id, share in optimisation.by_bucket.items():
            currency, bucket = parse_bucket_key(bucket_id)
            entry = ensure_currency_entry(currency)
            entry.by_bucket[bucket] = share
            entry.currency_share += share

        for (bucket_id, sleeve), value in optimisation.allocations.items():
            currency, bucket = parse_bucket_key(bucket_id)
            entry = ensure_currency_entry(currency)
            entry.allocations[(bucket, sleeve)] = value
            entry.by_sleeve[sleeve] = entry.by_sleeve.get(sleeve, 0.0) + value

        lines_map: dict[str, list[str]] = dict(inactive_currency_lines)

        overall_lines = [
            "Risk summary – all currencies (equal currency allocation enforced):",
            f"  Portfolio carry: {optimisation.portfolio_yield * 100:.2f}%",
            "  Equal per-bp risk:",
            f"    Rates DV01: {optimisation.K_rates:.6f}",
            f"    TIPS  DV01: {optimisation.K_tips:.6f}",
            f"    Credit CS01: {optimisation.K_credit:.6f}",
            "  Currency allocation targets:",
        ]

        for currency in currencies:
            entry = results_map.get(currency)
            if entry is not None:
                share_percent = entry.currency_share * 100.0
            else:
                share_percent = (
                    (currency_totals.get(currency, 0.0) / investable_total) * 100.0
                    if investable_total > 0.0
                    else 0.0
                )
            overall_lines.append(
                f"    {self._display_currency(currency)}: {share_percent:.2f}%"
            )

        lines_map["__overall__"] = overall_lines

        for currency in currencies:
            entry = results_map.get(currency)
            if not entry or math.isclose(entry.currency_share, 0.0, abs_tol=1e-9):
                continue
            selections = input_results.get(currency, {})
            lines = [
                f"Risk summary – {self._display_currency(currency)}:",
                f"  Target share: {entry.currency_share * 100:.2f}% of investable funds",
                "  Bucket weights considered:",
            ]
            for bucket in sorted(entry.by_bucket, key=lambda name: (-entry.by_bucket[name], name)):
                total_pct = entry.by_bucket[bucket] * 100.0
                if entry.currency_share > 0:
                    currency_pct = (entry.by_bucket[bucket] / entry.currency_share) * 100.0
                else:  # pragma: no cover - defensive
                    currency_pct = 0.0
                lines.append(
                    f"    {bucket}: {currency_pct:.2f}% of currency ({total_pct:.2f}% of total)"
                )

            lines.append("  Instruments used:")
            for bucket in sorted(selections):
                if bucket not in entry.by_bucket:
                    continue
                bucket_duration = horizon_to_years(bucket)
                for sleeve, (yield_value, tenor_value) in selections[bucket].items():
                    if yield_value is None:
                        continue
                    tenor_display = tenor_value if tenor_value is not None else bucket_duration
                    label = sleeve_labels.get(sleeve, sleeve.capitalize())
                    lines.append(
                        f"    {bucket}: {label} | Yield {yield_value:.2f}% | Tenor {tenor_display:.2f}y"
                    )

            lines.append("  Sleeve allocation (share of total investable funds):")
            for sleeve, total in sorted(entry.by_sleeve.items()):
                if total <= 0:
                    continue
                lines.append(f"    {sleeve.capitalize()}: {total * 100:.2f}%")

            lines_map[currency] = lines

        return lines_map, results_map

    def _build_plan(
        self,
        amount: float,
        tolerance: float,
        time_horizon: Optional[str],
        currency_filter: Optional[set[str]],
    ) -> tuple[list[PlanRow], dict[str, float], dict[str, dict[str, float]]]:
        allocations = self.repo.get_all_allocations()
        nodes: dict[int, TreeNode] = {}
        roots: list[TreeNode] = []
        for allocation in allocations:
            if allocation.id is None:
                continue
            nodes[allocation.id] = TreeNode(allocation=allocation, children=[])
        if not nodes:
            return (
                [],
                {
                    "current_total": 0.0,
                    "target_total": amount,
                    "invest_total": amount,
                    "divest_total": 0.0,
                },
                {},
            )

        for allocation in allocations:
            if allocation.id is None:
                continue
            node = nodes[allocation.id]
            if allocation.parent_id is None or allocation.parent_id not in nodes:
                roots.append(node)
            else:
                nodes[allocation.parent_id].children.append(node)

        def sort_children(items: Iterable[TreeNode]) -> None:
            for item in items:
                item.children.sort(key=lambda c: (c.allocation.sort_order, c.allocation.id or 0))
                sort_children(item.children)

        sort_children(roots)
        roots.sort(key=lambda n: (n.allocation.sort_order, n.allocation.id or 0))

        def normalize_horizon(value: Optional[str]) -> Optional[str]:
            if value is None:
                return None
            try:
                return canonicalize_time_horizon(value)
            except ValueError:
                stripped = value.strip() if isinstance(value, str) else ""
                return stripped if stripped else None

        time_horizon = normalize_horizon(time_horizon)
        contribute_cache: dict[tuple[int, Optional[str]], bool] = {}

        def select_currency_codes(value: Optional[str]) -> tuple[str, ...]:
            codes = self._parse_currency_codes(value)
            if currency_filter is None:
                return codes
            filtered = tuple(code for code in codes if code in currency_filter)
            return filtered

        def contributes(node: TreeNode, inherited: Optional[str]) -> bool:
            node_id = node.allocation.id if node.allocation.id is not None else id(node)
            key = (node_id, inherited)
            if key in contribute_cache:
                return contribute_cache[key]
            node_horizon = normalize_horizon(node.allocation.time_horizon) or inherited
            child_contributions = [contributes(child, node_horizon) for child in node.children]
            has_contributing_child = any(child_contributions)
            currency_codes = select_currency_codes(node.allocation.currency)
            currency_allowed = currency_filter is None or bool(currency_codes)
            matches_leaf = (
                node.allocation.include_in_rollup
                and not has_contributing_child
                and (time_horizon is None or node_horizon == time_horizon)
                and currency_allowed
            )
            result = matches_leaf or has_contributing_child
            contribute_cache[key] = result
            return result

        plan_rows: list[PlanRow] = []

        def gather(
            node: TreeNode,
            parent_share: float,
            path: list[str],
            inherited: Optional[str],
        ) -> None:
            allocation = node.allocation
            if allocation.id is None:
                return
            own_share = allocation.target_percent
            cumulative_share = parent_share * (own_share / 100.0)
            current_path = path + [allocation.name]
            node_horizon = normalize_horizon(allocation.time_horizon) or inherited
            included_children = [child for child in node.children if contributes(child, node_horizon)]
            currency_codes = select_currency_codes(allocation.currency)
            is_matching_leaf = (
                allocation.include_in_rollup
                and not included_children
                and (time_horizon is None or node_horizon == time_horizon)
                and (currency_filter is None or bool(currency_codes))
            )
            if is_matching_leaf:
                plan_rows.append(
                    PlanRow(
                        allocation_id=allocation.id,
                        path=" > ".join(current_path),
                        currencies=currency_codes if currency_codes else ("",),
                        time_horizon=node_horizon,
                        target_share=cumulative_share,
                        current_value=allocation.current_value,
                        current_share=0.0,
                        target_value=0.0,
                        recommended_change=0.0,
                        share_diff=0.0,
                        action="",
                    )
                )

            next_parent_share = cumulative_share

            for child in included_children:
                gather(child, next_parent_share, current_path, node_horizon)

        for root in roots:
            if contributes(root, None):
                gather(root, 100.0, [], None)

        total_target_share = sum(row.target_share for row in plan_rows)
        if math.isclose(total_target_share, 0.0, abs_tol=1e-9):
            for row in plan_rows:
                row.target_share = 0.0
        else:
            for row in plan_rows:
                row.target_share = row.target_share / total_target_share * 100.0

        total_current = sum(row.current_value for row in plan_rows)
        target_total = total_current + amount
        invest_total = 0.0
        divest_total = 0.0
        for row in plan_rows:
            row.current_share = (row.current_value / total_current * 100.0) if total_current else 0.0
            row.target_value = target_total * (row.target_share / 100.0)
            row.recommended_change = row.target_value - row.current_value
            row.share_diff = row.target_share - row.current_share
            if abs(row.share_diff) < tolerance:
                row.action = f"Within tolerance ({_format_share_delta(row.share_diff)})"
            elif row.recommended_change >= 0:
                row.action = f"Invest ({_format_share_delta(row.share_diff)})"
            else:
                row.action = f"Divest ({_format_share_delta(row.share_diff)})"
            if row.recommended_change >= 0:
                invest_total += row.recommended_change
            else:
                divest_total += row.recommended_change

        totals = {
            "current_total": total_current,
            "target_total": sum(row.target_value for row in plan_rows),
            "invest_total": invest_total,
            "divest_total": divest_total,
        }

        currency_totals: dict[str, dict[str, float]] = {}
        for row in plan_rows:
            codes = row.currencies if row.currencies else ("",)
            weight = 1.0 / max(len(codes), 1)
            for code in codes:
                bucket = currency_totals.setdefault(
                    code,
                    {
                        "current_total": 0.0,
                        "target_total": 0.0,
                        "invest_total": 0.0,
                        "divest_total": 0.0,
                    },
                )
                bucket["current_total"] += row.current_value * weight
                bucket["target_total"] += row.target_value * weight
                if row.recommended_change >= 0:
                    bucket["invest_total"] += row.recommended_change * weight
                else:
                    bucket["divest_total"] += row.recommended_change * weight

        return plan_rows, totals, currency_totals
    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _save_distribution(self) -> None:
        if not self.plan_rows:
            return
        name = self.distribution_name_var.get().strip()
        if not name:
            messagebox.showerror(
                "Missing name",
                "Please provide a name for the distribution before saving.",
                parent=self,
            )
            return

        try:
            risk_inputs = self.risk_editor.collect()
        except ValueError as exc:
            messagebox.showerror("Invalid risk inputs", str(exc), parent=self)
            self.risk_editor.set_status(str(exc))
            return

        for currency, result in risk_inputs.items():
            self._risk_inputs[currency] = result

        distribution = Distribution(
            id=None,
            name=name,
            total_amount=self.amount,
            tolerance_percent=self.tolerance,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        entries = [
            DistributionEntry(
                id=None,
                distribution_id=0,
                allocation_id=row.allocation_id,
                allocation_path=row.path,
                currency=row.currency,
                target_share=row.target_share,
                current_value=row.current_value,
                current_share=row.current_share,
                target_value=row.target_value,
                recommended_change=row.recommended_change,
                share_diff=row.share_diff,
                action=row.action,
            )
            for row in self.plan_rows
        ]

        risk_records = []
        for currency, horizons in risk_inputs.items():
            for horizon, sleeve_data in horizons.items():
                for sleeve, (yield_value, tenor_value) in sleeve_data.items():
                    risk_records.append(
                        DistributionRiskInput(
                            id=None,
                            distribution_id=0,
                            currency=currency,
                            time_horizon=horizon,
                            sleeve=sleeve,
                            yield_value=yield_value,
                            tenor_value=tenor_value,
                        )
                    )

        self.repo.create_distribution(distribution, entries, risk_records)
        self.on_saved(name, len(entries))
        messagebox.showinfo(
            "Distribution saved",
            f"Saved distribution '{name}' with {len(entries)} recommendation"
            f"{'s' if len(entries) != 1 else ''}.",
            parent=self,
        )
        self.save_button.config(state="disabled")

    def update_default_risk_inputs(
        self, defaults: dict[str, dict[str, dict[str, tuple[float, float]]]]
    ) -> None:
        self._manual_defaults = deepcopy(defaults)
        merged: dict[str, dict[str, dict[str, tuple[float, float]]]] = deepcopy(self._risk_inputs)
        for currency, horizons in self._manual_defaults.items():
            target_currency = merged.setdefault(currency, {})
            for horizon, sleeves in horizons.items():
                target_horizon = target_currency.setdefault(horizon, {})
                target_horizon.update(sleeves)
        self._risk_inputs = merged
        if self._last_horizon_requirements:
            self.risk_editor.set_requirements(self._last_horizon_requirements, self._risk_inputs)


class DistributionHistoryPanel(ttk.Frame):
    """Displays previously stored distribution plans inline."""

    def __init__(
        self,
        master: tk.Misc,
        repo: AllocationRepository,
        on_deleted: Callable[[str], None],
    ) -> None:
        super().__init__(master, padding=10)
        self.repo = repo
        self.on_deleted = on_deleted
        self.distributions: list[Distribution] = []

        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        paned = ttk.Panedwindow(container, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=1)
        paned.add(right, weight=3)

        ttk.Label(left, text="Distributions").pack(anchor="w")
        self.distribution_tree = ttk.Treeview(
            left,
            columns=("created", "amount", "tolerance"),
            show="headings",
            height=15,
        )
        self.distribution_tree.heading("created", text="Created")
        self.distribution_tree.heading("amount", text="Amount")
        self.distribution_tree.heading("tolerance", text="Tolerance")
        self.distribution_tree.column("created", width=170, anchor="w")
        self.distribution_tree.column("amount", width=100, anchor="e")
        self.distribution_tree.column("tolerance", width=90, anchor="e")
        dist_scroll = ttk.Scrollbar(left, orient="vertical", command=self.distribution_tree.yview)
        self.distribution_tree.configure(yscrollcommand=dist_scroll.set)
        self.distribution_tree.pack(side="left", fill="both", expand=True, pady=(4, 0))
        dist_scroll.pack(side="right", fill="y", pady=(4, 0))
        self.distribution_tree.bind("<<TreeviewSelect>>", self._on_distribution_select)

        ttk.Label(right, text="Recommendations").pack(anchor="w")
        columns = (
            "currency",
            "target_share",
            "current_value",
            "current_share",
            "target_value",
            "change",
            "share_diff",
            "action",
        )
        self.entries_tree = ttk.Treeview(
            right,
            columns=columns,
            show="tree headings",
            height=15,
        )
        self.entries_tree.heading("#0", text="Allocation")
        self.entries_tree.column("#0", width=320, anchor="w")
        self.entries_tree.heading("currency", text="Currency")
        self.entries_tree.column("currency", width=80, anchor="center")
        self.entries_tree.heading("target_share", text="Target %")
        self.entries_tree.column("target_share", width=90, anchor="e")
        self.entries_tree.heading("current_value", text="Current value")
        self.entries_tree.column("current_value", width=110, anchor="e")
        self.entries_tree.heading("current_share", text="Current %")
        self.entries_tree.column("current_share", width=90, anchor="e")
        self.entries_tree.heading("target_value", text="Target value")
        self.entries_tree.column("target_value", width=110, anchor="e")
        self.entries_tree.heading("change", text="Change")
        self.entries_tree.column("change", width=110, anchor="e")
        self.entries_tree.heading("share_diff", text="Δ share")
        self.entries_tree.column("share_diff", width=90, anchor="e")
        self.entries_tree.heading("action", text="Action")
        self.entries_tree.column("action", width=200, anchor="w")
        entries_scroll_y = ttk.Scrollbar(right, orient="vertical", command=self.entries_tree.yview)
        entries_scroll_x = ttk.Scrollbar(right, orient="horizontal", command=self.entries_tree.xview)
        self.entries_tree.configure(
            yscrollcommand=entries_scroll_y.set, xscrollcommand=entries_scroll_x.set
        )
        self.entries_tree.pack(side="left", fill="both", expand=True, pady=(4, 0))
        entries_scroll_y.pack(side="right", fill="y", pady=(4, 0))
        entries_scroll_x.pack(side="bottom", fill="x")

        risk_frame = ttk.LabelFrame(right, text="Risk inputs")
        risk_frame.pack(fill="x", pady=(10, 0))
        self.risk_tree = ttk.Treeview(
            risk_frame,
            columns=("currency", "horizon", "sleeve", "yield", "tenor"),
            show="headings",
            height=6,
        )
        self.risk_tree.heading("currency", text="Currency")
        self.risk_tree.heading("horizon", text="Horizon")
        self.risk_tree.heading("sleeve", text="Sleeve")
        self.risk_tree.heading("yield", text="Yield %")
        self.risk_tree.heading("tenor", text="Tenor (y)")
        self.risk_tree.column("currency", width=100, anchor="center")
        self.risk_tree.column("horizon", width=80, anchor="center")
        self.risk_tree.column("sleeve", width=140, anchor="w")
        self.risk_tree.column("yield", width=80, anchor="e")
        self.risk_tree.column("tenor", width=90, anchor="e")
        risk_scroll = ttk.Scrollbar(risk_frame, orient="vertical", command=self.risk_tree.yview)
        self.risk_tree.configure(yscrollcommand=risk_scroll.set)
        self.risk_tree.pack(side="left", fill="both", expand=True)
        risk_scroll.pack(side="right", fill="y")

        self.summary_var = tk.StringVar(
            value="Select a distribution to view its recommendations."
        )
        ttk.Label(right, textvariable=self.summary_var, anchor="w").pack(
            fill="x", pady=(8, 0)
        )

        button_row = ttk.Frame(container)
        button_row.pack(fill="x", pady=(10, 0))
        self.delete_button = ttk.Button(
            button_row,
            text="Delete selected",
            command=self._delete_selected,
            state="disabled",
        )
        self.delete_button.pack(side="left")
        ttk.Button(button_row, text="Refresh", command=self._load_distributions).pack(side="right")

        self._load_distributions()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self._load_distributions()

    def _load_distributions(self) -> None:
        self.distribution_tree.delete(*self.distribution_tree.get_children())
        self.distributions = self.repo.get_distributions()
        for distribution in self.distributions:
            self.distribution_tree.insert(
                "",
                "end",
                iid=str(distribution.id),
                values=(
                    self._format_timestamp(distribution.created_at),
                    _format_amount(distribution.total_amount),
                    _format_share_delta(distribution.tolerance_percent),
                ),
            )
        if not self.distributions:
            self.summary_var.set("No distributions saved yet.")
        self.delete_button.config(state="disabled")
        self.entries_tree.delete(*self.entries_tree.get_children())
        self.risk_tree.delete(*self.risk_tree.get_children())

    def _on_distribution_select(self, event: tk.Event[tk.EventType]) -> None:  # pragma: no cover
        selection = self.distribution_tree.selection()
        if not selection:
            self.entries_tree.delete(*self.entries_tree.get_children())
            self.summary_var.set("Select a distribution to view its recommendations.")
            self.delete_button.config(state="disabled")
            self.risk_tree.delete(*self.risk_tree.get_children())
            return
        dist_id = int(selection[0])
        distribution = next((d for d in self.distributions if d.id == dist_id), None)
        if not distribution:
            return
        entries = self.repo.get_distribution_entries(dist_id)
        risk_inputs = self.repo.get_distribution_risk_inputs(dist_id)
        self._populate_entries(distribution, entries, risk_inputs)
        self.delete_button.config(state="normal")

    def _populate_entries(
        self,
        distribution: Distribution,
        entries: List[DistributionEntry],
        risk_inputs: List[DistributionRiskInput],
    ) -> None:
        self.entries_tree.delete(*self.entries_tree.get_children())
        self.risk_tree.delete(*self.risk_tree.get_children())
        invest_total = 0.0
        divest_total = 0.0
        for entry in entries:
            self.entries_tree.insert(
                "",
                "end",
                iid=str(entry.id),
                text=entry.allocation_path,
                values=(
                    entry.currency,
                    _format_percent(entry.target_share),
                    _format_amount(entry.current_value),
                    _format_percent(entry.current_share),
                    _format_amount(entry.target_value),
                    _format_amount(entry.recommended_change),
                    _format_share_delta(entry.share_diff),
                    entry.action,
                ),
            )
            if entry.recommended_change >= 0:
                invest_total += entry.recommended_change
            else:
                divest_total += entry.recommended_change

        sleeve_labels = {
            "rates": "Government (DV01)",
            "tips": "Inflation (BE01)",
            "credit": "Credit (CS01)",
        }
        for record in sorted(
            risk_inputs,
            key=lambda item: (
                (item.currency or ""),
                item.time_horizon,
                item.sleeve,
            ),
        ):
            display_currency = self._display_currency(record.currency)
            display_sleeve = sleeve_labels.get(record.sleeve, record.sleeve.title())
            yield_text = f"{record.yield_value:.2f}" if record.yield_value is not None else ""
            tenor_text = f"{record.tenor_value:.2f}" if record.tenor_value is not None else ""
            self.risk_tree.insert(
                "",
                "end",
                values=(
                    display_currency,
                    record.time_horizon,
                    display_sleeve,
                    yield_text,
                    tenor_text,
                ),
            )

        summary_lines = [
            f"Created: {self._format_timestamp(distribution.created_at)}",
            f"Recorded amount: {_format_amount(distribution.total_amount)}",
            f"Tolerance: {_format_share_delta(distribution.tolerance_percent)}",
            f"Invest: {_format_amount(invest_total)} | Divest: {_format_amount(abs(divest_total))}",
        ]
        if risk_inputs:
            summary_lines.append(
                f"Risk inputs captured: {len(risk_inputs)}"
            )
        self.summary_var.set("\n".join(summary_lines))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _delete_selected(self) -> None:
        selection = self.distribution_tree.selection()
        if not selection:
            return
        dist_id = int(selection[0])
        distribution = next((d for d in self.distributions if d.id == dist_id), None)
        if not distribution:
            return
        if not messagebox.askyesno(
            "Delete distribution",
            f"Delete distribution '{distribution.name}'? This action cannot be undone.",
            parent=self,
        ):
            return
        self.repo.delete_distribution(dist_id)
        self.on_deleted(distribution.name)
        self._load_distributions()
        self.summary_var.set("Distribution deleted.")

    @staticmethod
    def _format_timestamp(value: str) -> str:
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
        except ValueError:  # pragma: no cover - fallback for unexpected formats
            return value

    @staticmethod
    def _display_currency(value: str) -> str:
        return value or "Unspecified"


def run_app() -> None:  # pragma: no cover - convenience wrapper for CLI usage
    root = tk.Tk()
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure("Treeview", rowheight=24)
    AllocationApp(root)
    root.minsize(960, 600)
    root.mainloop()


DistributionDialog = DistributionPanel
DistributionHistoryDialog = DistributionHistoryPanel


if __name__ == "__main__":  # pragma: no cover - manual launch only
    run_app()
