"""Tkinter user interface for managing hierarchical money allocations."""
from __future__ import annotations

import csv
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable, Dict, Iterable, List, Optional

from .db import AllocationRepository
from .models import Allocation, Distribution, DistributionEntry
from .sample_data import populate_with_sample_data


@dataclass
class TreeNode:
    allocation: Allocation
    children: list["TreeNode"]


@dataclass(slots=True)
class PlanRow:
    """Represents a single recommendation entry in the allocation plan."""

    allocation_id: int
    path: str
    currency: str
    target_share: float
    current_value: float
    current_share: float
    target_value: float
    recommended_change: float
    share_diff: float
    action: str


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
        self.percent_var = tk.StringVar()
        self.value_var = tk.StringVar()
        self.include_var = tk.BooleanVar(value=True)
        self.path_var = tk.StringVar(value="No selection")
        self.child_sum_var = tk.StringVar(value="Children share: 0.00% of parent")
        self.status_var = tk.StringVar(value="Welcome! Use the buttons above to manage allocations.")

        self.grid(column=0, row=0, sticky="nsew")
        self.master.rowconfigure(0, weight=1)
        self.master.columnconfigure(0, weight=1)

        self._create_menu()
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

        tools_menu = tk.Menu(menubar, tearoff=False)
        tools_menu.add_command(label="Distribute funds…", command=self._open_distribution_dialog)
        tools_menu.add_command(label="Distribution history…", command=self._open_distribution_history)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        self.master.config(menu=menubar)

    def _create_widgets(self) -> None:
        # Toolbar with common actions
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
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

        # Tree view with scrollbars
        tree_frame = ttk.Frame(self)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        columns = ("currency", "target", "cumulative", "included")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Allocation")
        self.tree.heading("currency", text="Currency")
        self.tree.heading("target", text="Share of parent")
        self.tree.heading("cumulative", text="Share of total")
        self.tree.heading("included", text="Included")
        self.tree.column("#0", width=240)
        self.tree.column("currency", width=80, anchor="center")
        self.tree.column("target", width=120, anchor="e")
        self.tree.column("cumulative", width=120, anchor="e")
        self.tree.column("included", width=80, anchor="center")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.grid(row=0, column=0, sticky="nsew")

        tree_scroll_y = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")

        # Editor form
        form = ttk.LabelFrame(self, text="Allocation details")
        form.grid(row=1, column=1, padx=(10, 0), sticky="nsew")
        form.columnconfigure(1, weight=1)
        form.rowconfigure(6, weight=1)

        ttk.Label(form, text="Path:").grid(row=0, column=0, sticky="w")
        ttk.Label(form, textvariable=self.path_var, wraplength=260).grid(row=0, column=1, sticky="w")

        ttk.Label(form, text="Name:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.name_entry = ttk.Entry(form, textvariable=self.name_var, width=30)
        self.name_entry.grid(row=1, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(form, text="Currency:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.currency_entry = ttk.Entry(form, textvariable=self.currency_var)
        self.currency_entry.grid(row=2, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(form, text="Share of parent (%):").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.percent_entry = ttk.Entry(form, textvariable=self.percent_var)
        self.percent_entry.grid(row=3, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(form, text="Current value:").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.value_entry = ttk.Entry(form, textvariable=self.value_var)
        self.value_entry.grid(row=4, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(form, text="Included in roll-up:").grid(row=5, column=0, sticky="w", pady=(6, 0))
        self.include_check = ttk.Checkbutton(form, variable=self.include_var, text="Yes")
        self.include_check.grid(row=5, column=1, sticky="w", pady=(6, 0))

        ttk.Label(form, text="Notes:").grid(row=6, column=0, sticky="nw", pady=(6, 0))
        self.notes_text = tk.Text(form, height=8, wrap="word")
        self.notes_text.grid(row=6, column=1, sticky="nsew", pady=(6, 0))
        notes_scroll = ttk.Scrollbar(form, orient="vertical", command=self.notes_text.yview)
        self.notes_text.configure(yscrollcommand=notes_scroll.set)
        notes_scroll.grid(row=6, column=2, sticky="nsw")

        ttk.Label(form, textvariable=self.child_sum_var).grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # Status bar
        status = ttk.Label(self, textvariable=self.status_var, anchor="w")
        status.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)

        self._set_form_state(False)

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
                    if not row["name"].strip():
                        continue
                    allocations.append(
                        Allocation(
                            id=int(row["id"]) if row["id"].strip() else None,
                            parent_id=int(row["parent_id"]) if row["parent_id"].strip() else None,
                            name=row["name"].strip(),
                            currency=row["currency"].strip() or None,
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
        include = bool(self.include_var.get())

        if self.mode == "add":
            parent_id = self.parent_for_new
            sort_order = self.repo.get_next_sort_order(parent_id)
            allocation = Allocation(
                id=None,
                parent_id=parent_id,
                name=name,
                currency=currency,
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
    def _open_distribution_dialog(self) -> None:
        DistributionDialog(self.master, self.repo, self._on_distribution_saved)

    def _open_distribution_history(self) -> None:
        DistributionHistoryDialog(self.master, self.repo, self._on_distribution_deleted)

    def _on_distribution_saved(self, name: str, count: int) -> None:
        self.status_var.set(
            f"Saved distribution '{name}' with {count} recommendation{'s' if count != 1 else ''}."
        )

    def _on_distribution_deleted(self, name: str) -> None:
        self.status_var.set(f"Deleted distribution '{name}'.")

    # ------------------------------------------------------------------
    # Tree interactions
    # ------------------------------------------------------------------
    def refresh_tree(self, *, select_id: Optional[int] = None) -> None:
        self.tree.delete(*self.tree.get_children())
        allocations = self.repo.get_all_allocations()
        self.allocation_cache = {allocation.id: allocation for allocation in allocations}

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
            ),
            open=True,
        )
        next_parent_share = cumulative if allocation.include_in_rollup else parent_share
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
        for entry in (self.name_entry, self.currency_entry, self.percent_entry, self.value_entry):
            entry.config(state=state)
        self.include_check.config(state=state)
        if enabled:
            self.notes_text.config(state="normal")
        else:
            self.notes_text.config(state="disabled")

    def _clear_form(self) -> None:
        self.name_var.set("")
        self.currency_var.set("")
        self.percent_var.set("0")
        self.value_var.set("0")
        self.include_var.set(True)
        self.notes_text.config(state="normal")
        self.notes_text.delete("1.0", "end")
        self.notes_text.config(state="disabled")

    def _fill_form(self, allocation: Allocation) -> None:
        self.name_var.set(allocation.name)
        self.currency_var.set(allocation.normalized_currency)
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


class DistributionDialog(tk.Toplevel):
    """Dialog that calculates and persists distribution recommendations."""

    def __init__(
        self,
        master: tk.Misc,
        repo: AllocationRepository,
        on_saved: Callable[[str, int], None],
    ) -> None:
        super().__init__(master)
        self.repo = repo
        self.on_saved = on_saved
        self.plan_rows: list[PlanRow] = []
        self.amount: float = 0.0
        self.tolerance: float = 0.0
        self.totals: dict[str, float] = {
            "current_total": 0.0,
            "target_total": 0.0,
            "invest_total": 0.0,
            "divest_total": 0.0,
        }

        self.amount_var = tk.StringVar(value="0")
        self.tolerance_var = tk.StringVar(value="2.0")
        self.summary_var = tk.StringVar(value="Enter an amount and press Calculate.")

        self.title("Distribute funds")
        self.transient(master)
        self.grab_set()
        self.resizable(True, True)

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)

        form = ttk.Frame(container)
        form.pack(fill="x")
        form.columnconfigure(4, weight=1)

        ttk.Label(form, text="Amount to distribute:").grid(row=0, column=0, sticky="w")
        amount_entry = ttk.Entry(form, textvariable=self.amount_var, width=18)
        amount_entry.grid(row=0, column=1, sticky="w", padx=(4, 12))

        ttk.Label(form, text="Tolerance (pp):").grid(row=0, column=2, sticky="w")
        ttk.Entry(form, textvariable=self.tolerance_var, width=10).grid(
            row=0, column=3, sticky="w", padx=(4, 12)
        )

        ttk.Button(form, text="Calculate", command=self._calculate_plan).grid(
            row=0, column=4, sticky="e"
        )

        tree_frame = ttk.Frame(container)
        tree_frame.pack(fill="both", expand=True, pady=(10, 0))
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
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", height=15)
        self.tree.heading("#0", text="Allocation")
        self.tree.column("#0", width=320, anchor="w")
        self.tree.heading("currency", text="Currency")
        self.tree.column("currency", width=80, anchor="center")
        self.tree.heading("target_share", text="Target %")
        self.tree.column("target_share", width=90, anchor="e")
        self.tree.heading("current_value", text="Current value")
        self.tree.column("current_value", width=110, anchor="e")
        self.tree.heading("current_share", text="Current %")
        self.tree.column("current_share", width=90, anchor="e")
        self.tree.heading("target_value", text="Target value")
        self.tree.column("target_value", width=110, anchor="e")
        self.tree.heading("change", text="Change")
        self.tree.column("change", width=110, anchor="e")
        self.tree.heading("share_diff", text="Δ share")
        self.tree.column("share_diff", width=90, anchor="e")
        self.tree.heading("action", text="Action")
        self.tree.column("action", width=200, anchor="w")

        tree_scroll_y = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        ttk.Label(container, textvariable=self.summary_var, anchor="w").pack(
            fill="x", pady=(10, 0)
        )

        button_row = ttk.Frame(container)
        button_row.pack(fill="x", pady=(10, 0))
        self.save_button = ttk.Button(
            button_row,
            text="Save distribution",
            command=self._save_distribution,
            state="disabled",
        )
        self.save_button.pack(side="left")
        ttk.Button(button_row, text="Close", command=self.destroy).pack(side="right")

        amount_entry.focus_set()

    # ------------------------------------------------------------------
    # Plan calculation
    # ------------------------------------------------------------------
    def _calculate_plan(self) -> None:
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

        plan_rows, totals = self._build_plan(amount, tolerance)
        if not plan_rows:
            messagebox.showinfo(
                "No included allocations",
                "None of the allocations are marked as included in the roll-up, therefore no "
                "distribution recommendations can be produced.",
                parent=self,
            )
            self.tree.delete(*self.tree.get_children())
            self.summary_var.set("No plan available. Update your allocations and try again.")
            self.save_button.config(state="disabled")
            self.plan_rows = []
            return

        self.plan_rows = plan_rows
        self.amount = amount
        self.tolerance = tolerance
        self.totals = totals
        self._populate_tree()
        self.save_button.config(state="normal")

    def _populate_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for row in self.plan_rows:
            self.tree.insert(
                "",
                "end",
                iid=str(row.allocation_id),
                text=row.path,
                values=(
                    row.currency,
                    _format_percent(row.target_share),
                    _format_amount(row.current_value),
                    _format_percent(row.current_share),
                    _format_amount(row.target_value),
                    _format_amount(row.recommended_change),
                    _format_share_delta(row.share_diff),
                    row.action,
                ),
            )

        invest_total = self.totals.get("invest_total", 0.0)
        divest_total = abs(self.totals.get("divest_total", 0.0))
        summary_lines = [
            f"Current total: {_format_amount(self.totals.get('current_total', 0.0))}",
            f"Target total: {_format_amount(self.totals.get('target_total', 0.0))} (deposit {_format_amount(self.amount)})",
            f"Invest: {_format_amount(invest_total)} | Divest: {_format_amount(divest_total)}",
        ]
        self.summary_var.set("\n".join(summary_lines))

    def _build_plan(self, amount: float, tolerance: float) -> tuple[list[PlanRow], dict[str, float]]:
        allocations = self.repo.get_all_allocations()
        nodes: dict[int, TreeNode] = {}
        roots: list[TreeNode] = []
        for allocation in allocations:
            if allocation.id is None:
                continue
            nodes[allocation.id] = TreeNode(allocation=allocation, children=[])
        if not nodes:
            return [], {
                "current_total": 0.0,
                "target_total": amount,
                "invest_total": amount,
                "divest_total": 0.0,
            }

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

        contribute_cache: dict[int, bool] = {}

        def contributes(node: TreeNode) -> bool:
            key = node.allocation.id if node.allocation.id is not None else id(node)
            if key in contribute_cache:
                return contribute_cache[key]
            contributes_value = node.allocation.include_in_rollup or any(
                contributes(child) for child in node.children
            )
            contribute_cache[key] = contributes_value
            return contributes_value

        plan_rows: list[PlanRow] = []

        def gather(node: TreeNode, parent_share: float, path: list[str]) -> None:
            allocation = node.allocation
            if allocation.id is None:
                return
            own_share = allocation.target_percent
            cumulative_share = parent_share * (own_share / 100.0)
            current_path = path + [allocation.name]
            included_children = [child for child in node.children if contributes(child)]
            if allocation.include_in_rollup and not included_children:
                plan_rows.append(
                    PlanRow(
                        allocation_id=allocation.id,
                        path=" > ".join(current_path),
                        currency=allocation.normalized_currency,
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
                gather(child, next_parent_share, current_path)

        for root in roots:
            if contributes(root):
                gather(root, 100.0, [])

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
            "target_total": target_total,
            "invest_total": invest_total,
            "divest_total": divest_total,
        }
        return plan_rows, totals

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _save_distribution(self) -> None:
        if not self.plan_rows:
            return
        default_name = datetime.now().strftime("Distribution %Y-%m-%d %H:%M")
        name = simpledialog.askstring(
            "Save distribution",
            "Distribution name:",
            parent=self,
            initialvalue=default_name,
        )
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showerror("Missing name", "Please provide a name for the distribution.", parent=self)
            return

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

        self.repo.create_distribution(distribution, entries)
        self.on_saved(name, len(entries))
        messagebox.showinfo(
            "Distribution saved",
            f"Saved distribution '{name}' with {len(entries)} recommendation"
            f"{'s' if len(entries) != 1 else ''}.",
            parent=self,
        )
        self.save_button.config(state="disabled")


class DistributionHistoryDialog(tk.Toplevel):
    """Displays previously stored distribution plans."""

    def __init__(
        self,
        master: tk.Misc,
        repo: AllocationRepository,
        on_deleted: Callable[[str], None],
    ) -> None:
        super().__init__(master)
        self.repo = repo
        self.on_deleted = on_deleted
        self.distributions: list[Distribution] = []

        self.title("Distribution history")
        self.transient(master)
        self.grab_set()
        self.resizable(True, True)

        container = ttk.Frame(self, padding=10)
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
        ttk.Button(button_row, text="Close", command=self.destroy).pack(side="right")

        self._load_distributions()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
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

    def _on_distribution_select(self, event: tk.Event[tk.EventType]) -> None:  # pragma: no cover
        selection = self.distribution_tree.selection()
        if not selection:
            self.entries_tree.delete(*self.entries_tree.get_children())
            self.summary_var.set("Select a distribution to view its recommendations.")
            self.delete_button.config(state="disabled")
            return
        dist_id = int(selection[0])
        distribution = next((d for d in self.distributions if d.id == dist_id), None)
        if not distribution:
            return
        entries = self.repo.get_distribution_entries(dist_id)
        self._populate_entries(distribution, entries)
        self.delete_button.config(state="normal")

    def _populate_entries(
        self, distribution: Distribution, entries: List[DistributionEntry]
    ) -> None:
        self.entries_tree.delete(*self.entries_tree.get_children())
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

        summary_lines = [
            f"Created: {self._format_timestamp(distribution.created_at)}",
            f"Recorded amount: {_format_amount(distribution.total_amount)}",
            f"Tolerance: {_format_share_delta(distribution.tolerance_percent)}",
            f"Invest: {_format_amount(invest_total)} | Divest: {_format_amount(abs(divest_total))}",
        ]
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


def run_app() -> None:  # pragma: no cover - convenience wrapper for CLI usage
    root = tk.Tk()
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure("Treeview", rowheight=24)
    AllocationApp(root)
    root.minsize(960, 600)
    root.mainloop()


if __name__ == "__main__":  # pragma: no cover - manual launch only
    run_app()
