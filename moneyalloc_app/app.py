"""Tkinter user interface for managing hierarchical money allocations."""
from __future__ import annotations

import csv
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, Iterable, Optional

from .db import AllocationRepository
from .models import Allocation
from .sample_data import populate_with_sample_data


@dataclass
class TreeNode:
    allocation: Allocation
    children: list["TreeNode"]


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

        ttk.Label(form, text="Included in roll-up:").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.include_check = ttk.Checkbutton(form, variable=self.include_var, text="Yes")
        self.include_check.grid(row=4, column=1, sticky="w", pady=(6, 0))

        ttk.Label(form, text="Notes:").grid(row=5, column=0, sticky="nw", pady=(6, 0))
        self.notes_text = tk.Text(form, height=8, wrap="word")
        self.notes_text.grid(row=5, column=1, sticky="nsew", pady=(6, 0))
        notes_scroll = ttk.Scrollbar(form, orient="vertical", command=self.notes_text.yview)
        self.notes_text.configure(yscrollcommand=notes_scroll.set)
        notes_scroll.grid(row=5, column=2, sticky="nsw")

        ttk.Label(form, textvariable=self.child_sum_var).grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))

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
                required = {"id", "parent_id", "name", "currency", "target_percent", "include_in_rollup", "notes", "sort_order"}
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
        for entry in (self.name_entry, self.currency_entry, self.percent_entry):
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
        self.include_var.set(True)
        self.notes_text.config(state="normal")
        self.notes_text.delete("1.0", "end")
        self.notes_text.config(state="disabled")

    def _fill_form(self, allocation: Allocation) -> None:
        self.name_var.set(allocation.name)
        self.currency_var.set(allocation.normalized_currency)
        self.percent_var.set(f"{allocation.target_percent:.2f}")
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
