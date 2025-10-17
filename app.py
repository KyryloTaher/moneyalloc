"""Tkinter UI for the Moneyalloc tool."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, Optional

from moneyalloc import allocation
from moneyalloc.database import AllocationRecord, Database, TenorInputRecord


class MoneyAllocApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Money Allocation Tool")
        self.geometry("1024x720")

        self.db = Database()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab1 = ttk.Frame(self.notebook)
        self.tab2 = ttk.Frame(self.notebook)
        self.tab3 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab1, text="Distributions")
        self.notebook.add(self.tab2, text="Buckets")
        self.notebook.add(self.tab3, text="Results")

        self._setup_tab1()
        self._setup_tab2()
        self._setup_tab3()

        self.refresh_tree()
        self.refresh_buckets()
        self.refresh_results()

    # ------------------------------------------------------------------ Tab 1
    def _setup_tab1(self) -> None:
        frame = self.tab1
        left_frame = ttk.Frame(frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ("name", "percentage", "leaf")
        self.tree = ttk.Treeview(left_frame, columns=columns, show="tree headings", height=20)
        self.tree.heading("name", text="Name")
        self.tree.heading("percentage", text="%")
        self.tree.heading("leaf", text="Leaf")
        self.tree.column("name", width=200)
        self.tree.column("percentage", width=80)
        self.tree.column("leaf", width=60)
        self.tree.pack(fill=tk.BOTH, expand=True)

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        right_frame = ttk.Frame(frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)

        ttk.Label(right_frame, text="Name").pack(anchor=tk.W)
        self.name_entry = ttk.Entry(right_frame)
        self.name_entry.pack(fill=tk.X)

        ttk.Label(right_frame, text="Percentage").pack(anchor=tk.W, pady=(10, 0))
        self.percentage_entry = ttk.Entry(right_frame)
        self.percentage_entry.insert(0, "100")
        self.percentage_entry.pack(fill=tk.X)

        self.is_leaf_var = tk.BooleanVar(value=True)
        leaf_check = ttk.Checkbutton(right_frame, text="Leaf node", variable=self.is_leaf_var, command=self.on_leaf_toggle)
        leaf_check.pack(anchor=tk.W, pady=(10, 0))

        ttk.Label(right_frame, text="Currencies (comma separated)").pack(anchor=tk.W, pady=(10, 0))
        self.currencies_entry = ttk.Entry(right_frame)
        self.currencies_entry.pack(fill=tk.X)

        ttk.Label(right_frame, text="Time horizon (years)").pack(anchor=tk.W, pady=(10, 0))
        self.time_horizon_entry = ttk.Entry(right_frame)
        self.time_horizon_entry.pack(fill=tk.X)

        button_frame = ttk.Frame(right_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))

        ttk.Button(button_frame, text="Add root", command=self.add_root).pack(fill=tk.X)
        ttk.Button(button_frame, text="Add child", command=self.add_child).pack(fill=tk.X, pady=5)
        ttk.Button(button_frame, text="Update", command=self.update_node).pack(fill=tk.X)
        ttk.Button(button_frame, text="Delete", command=self.delete_node).pack(fill=tk.X, pady=5)
        ttk.Button(button_frame, text="Generate buckets", command=self.generate_buckets).pack(fill=tk.X, pady=(15, 0))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(right_frame, textvariable=self.status_var, wraplength=200).pack(anchor=tk.W, pady=(20, 0))

    def on_leaf_toggle(self) -> None:
        state = tk.NORMAL if self.is_leaf_var.get() else tk.DISABLED
        for widget in (self.currencies_entry, self.time_horizon_entry):
            widget.configure(state=state)

    def refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.tree_id_map: Dict[str, int] = {}
        allocations = self.db.get_allocations()
        by_parent: Dict[Optional[int], list[AllocationRecord]] = {}
        for allocation_record in allocations:
            by_parent.setdefault(allocation_record.parent_id, []).append(allocation_record)

        def insert_children(parent_tree_id: Optional[str], parent_id: Optional[int]) -> None:
            for record in by_parent.get(parent_id, []):
                tree_parent = parent_tree_id or ""
                tree_id = self.tree.insert(
                    tree_parent,
                    tk.END,
                    text=record.name,
                    values=(record.name, f"{record.percentage:.2f}", "Yes" if record.is_leaf else "No"),
                )
                self.tree_id_map[tree_id] = record.id
                insert_children(tree_id, record.id)

        insert_children("", None)

    def on_tree_select(self, event: tk.Event) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        tree_id = selected[0]
        allocation_id = self.tree_id_map.get(tree_id)
        if allocation_id is None:
            return
        record = next((r for r in self.db.get_allocations() if r.id == allocation_id), None)
        if not record:
            return
        self.name_entry.delete(0, tk.END)
        self.name_entry.insert(0, record.name)
        self.percentage_entry.delete(0, tk.END)
        self.percentage_entry.insert(0, str(record.percentage))
        self.is_leaf_var.set(record.is_leaf)
        for widget in (self.currencies_entry, self.time_horizon_entry):
            widget.configure(state=tk.NORMAL)
        self.currencies_entry.delete(0, tk.END)
        self.currencies_entry.insert(0, record.currencies)
        self.time_horizon_entry.delete(0, tk.END)
        self.time_horizon_entry.insert(0, "" if record.time_horizon is None else str(record.time_horizon))
        self.on_leaf_toggle()

    def _read_form(self) -> tuple[str, float, bool, str, Optional[float]]:
        name = self.name_entry.get().strip()
        if not name:
            raise ValueError("Name is required")
        try:
            percentage = float(self.percentage_entry.get())
        except ValueError as exc:
            raise ValueError("Percentage must be numeric") from exc
        percentage = allocation.normalise_percentage(percentage)
        is_leaf = self.is_leaf_var.get()
        currencies = self.currencies_entry.get().strip()
        time_horizon: Optional[float] = None
        if is_leaf:
            if not currencies:
                raise ValueError("Currencies required for leaf nodes")
            try:
                time_horizon = float(self.time_horizon_entry.get())
            except ValueError as exc:
                raise ValueError("Time horizon must be numeric") from exc
        return name, percentage, is_leaf, currencies, time_horizon

    def add_root(self) -> None:
        try:
            name, percentage, is_leaf, currencies, time_horizon = self._read_form()
        except ValueError as error:
            messagebox.showerror("Invalid input", str(error))
            return
        allocation_id = self.db.add_allocation(
            parent_id=None,
            name=name,
            percentage=percentage,
            currencies=currencies,
            time_horizon=time_horizon,
            is_leaf=is_leaf,
        )
        self.refresh_tree()
        self.status_var.set(f"Added root allocation #{allocation_id}")

    def _get_selected_allocation_id(self) -> Optional[int]:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.tree_id_map.get(selection[0])

    def add_child(self) -> None:
        parent_id = self._get_selected_allocation_id()
        if parent_id is None:
            messagebox.showinfo("Select parent", "Please select a parent node in the tree")
            return
        try:
            name, percentage, is_leaf, currencies, time_horizon = self._read_form()
        except ValueError as error:
            messagebox.showerror("Invalid input", str(error))
            return
        allocation_id = self.db.add_allocation(
            parent_id=parent_id,
            name=name,
            percentage=percentage,
            currencies=currencies,
            time_horizon=time_horizon,
            is_leaf=is_leaf,
        )
        self.refresh_tree()
        self.status_var.set(f"Added child allocation #{allocation_id}")

    def update_node(self) -> None:
        allocation_id = self._get_selected_allocation_id()
        if allocation_id is None:
            messagebox.showinfo("Select node", "Please select a node to update")
            return
        try:
            name, percentage, is_leaf, currencies, time_horizon = self._read_form()
        except ValueError as error:
            messagebox.showerror("Invalid input", str(error))
            return
        self.db.update_allocation(
            allocation_id,
            name=name,
            percentage=percentage,
            currencies=currencies,
            time_horizon=time_horizon,
            is_leaf=is_leaf,
        )
        self.refresh_tree()
        self.status_var.set(f"Updated allocation #{allocation_id}")

    def delete_node(self) -> None:
        allocation_id = self._get_selected_allocation_id()
        if allocation_id is None:
            messagebox.showinfo("Select node", "Please select a node to delete")
            return
        if not messagebox.askyesno("Confirm deletion", "Delete selected allocation and its children?"):
            return
        self.db.delete_allocation(allocation_id)
        self.refresh_tree()
        self.status_var.set(f"Deleted allocation #{allocation_id}")

    def generate_buckets(self) -> None:
        allocations = self.db.get_allocations()
        if not allocations:
            messagebox.showinfo("No allocations", "Add at least one allocation before generating buckets")
            return
        leaves = allocation.build_leaf_allocations(allocations)
        buckets = allocation.build_bucket_records(leaves)
        if not buckets:
            messagebox.showinfo("No leaves", "No leaf allocations available to build buckets")
            return
        self.db.clear_buckets()
        self.db.save_buckets(buckets)
        self.refresh_buckets()
        messagebox.showinfo("Buckets generated", "Allocation buckets have been updated")
        self.notebook.select(self.tab2)

    # ------------------------------------------------------------------ Tab 2
    def _setup_tab2(self) -> None:
        frame = self.tab2
        header_frame = ttk.Frame(frame)
        header_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(header_frame, text="Total investment amount").grid(row=0, column=0, sticky=tk.W)
        self.total_amount_entry = ttk.Entry(header_frame)
        total_amount = self.db.get_setting("total_amount") or ""
        self.total_amount_entry.insert(0, total_amount)
        self.total_amount_entry.grid(row=1, column=0, sticky=tk.EW)

        button_frame = ttk.Frame(header_frame)
        button_frame.grid(row=0, column=1, rowspan=2, padx=(10, 0), sticky=tk.NE)
        ttk.Button(button_frame, text="Save tenor inputs", command=self.save_tenor_inputs).pack(fill=tk.X)
        ttk.Button(button_frame, text="Calculate", command=self.calculate).pack(fill=tk.X, pady=(5, 0))

        header_frame.columnconfigure(0, weight=1)

        self.bucket_canvas = tk.Canvas(frame)
        self.bucket_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.bucket_canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.bucket_canvas.configure(yscrollcommand=scrollbar.set)

        self.bucket_inner = ttk.Frame(self.bucket_canvas)
        self.bucket_canvas.create_window((0, 0), window=self.bucket_inner, anchor="nw")
        self.bucket_inner.bind("<Configure>", lambda e: self.bucket_canvas.configure(scrollregion=self.bucket_canvas.bbox("all")))

        self.bucket_rows: Dict[str, Dict[str, tk.Entry]] = {}

    def refresh_buckets(self) -> None:
        for child in list(self.bucket_inner.children.values()):
            child.destroy()
        self.bucket_rows.clear()

        buckets = self.db.get_buckets()
        tenor_inputs = self.db.get_tenor_inputs()

        if not buckets:
            ttk.Label(self.bucket_inner, text="No buckets available. Generate buckets first.").grid(row=0, column=0, sticky=tk.W)
            return

        headers = ["Bucket", "Percentage", "DV01 tenors", "BEI01 tenors", "CS01 tenors"]
        for col, text in enumerate(headers):
            ttk.Label(self.bucket_inner, text=text, font=("TkDefaultFont", 10, "bold")).grid(row=0, column=col, sticky=tk.W, padx=5, pady=2)

        for row_index, bucket in enumerate(buckets, start=1):
            bucket_key = bucket.bucket_key
            percentage_text = f"{bucket.percentage:.2f}%"
            bucket_label = f"{bucket.currency} / {bucket.time_horizon}y"
            ttk.Label(self.bucket_inner, text=bucket_label).grid(row=row_index, column=0, sticky=tk.W, padx=5, pady=2)
            ttk.Label(self.bucket_inner, text=percentage_text).grid(row=row_index, column=1, sticky=tk.W, padx=5, pady=2)

            row_entries: Dict[str, tk.Entry] = {}
            record = tenor_inputs.get(bucket_key, TenorInputRecord(bucket_key, "", "", ""))
            for col_index, field in enumerate(["dv01_tenors", "bei01_tenors", "cs01_tenors"], start=2):
                entry = ttk.Entry(self.bucket_inner, width=25)
                entry.insert(0, getattr(record, field))
                entry.grid(row=row_index, column=col_index, sticky=tk.W, padx=5, pady=2)
                row_entries[field] = entry
            self.bucket_rows[bucket_key] = row_entries

    def save_tenor_inputs(self, show_message: bool = True) -> None:
        for bucket_key, entries in self.bucket_rows.items():
            dv01 = entries["dv01_tenors"].get().strip()
            bei01 = entries["bei01_tenors"].get().strip()
            cs01 = entries["cs01_tenors"].get().strip()
            self.db.save_tenor_input(
                bucket_key,
                dv01_tenors=dv01,
                bei01_tenors=bei01,
                cs01_tenors=cs01,
            )
        self.db.set_setting("total_amount", self.total_amount_entry.get().strip())
        if show_message:
            messagebox.showinfo("Saved", "Tenor inputs saved")

    def calculate(self) -> None:
        try:
            total_amount = float(self.total_amount_entry.get())
        except ValueError:
            messagebox.showerror("Invalid amount", "Total investment amount must be numeric")
            return

        self.save_tenor_inputs(show_message=False)

        buckets = self.db.get_buckets()
        tenor_records = self.db.get_tenor_inputs()

        tenor_inputs: Dict[str, Dict[str, list[float]]] = {}
        for bucket in buckets:
            record = tenor_records.get(bucket.bucket_key)
            if record:
                tenor_inputs[bucket.bucket_key] = {
                    "DV01": allocation.parse_tenor_string(record.dv01_tenors),
                    "BEI01": allocation.parse_tenor_string(record.bei01_tenors),
                    "CS01": allocation.parse_tenor_string(record.cs01_tenors),
                }
            else:
                tenor_inputs[bucket.bucket_key] = {
                    "DV01": [],
                    "BEI01": [],
                    "CS01": [],
                }

        results = allocation.calculate_results(buckets, tenor_inputs, total_amount)
        self.db.clear_results()
        self.db.save_results(results)
        self.refresh_results()
        self.notebook.select(self.tab3)
        messagebox.showinfo("Calculation complete", "Risk balancing complete")

    # ------------------------------------------------------------------ Tab 3
    def _setup_tab3(self) -> None:
        frame = self.tab3
        columns = ("bucket", "amount", "dv01", "bei01", "cs01", "exposure")
        self.result_tree = ttk.Treeview(frame, columns=columns, show="headings", height=20)
        headings = {
            "bucket": "Bucket",
            "amount": "Amount",
            "dv01": "DV01 tenor",
            "bei01": "BEI01 tenor",
            "cs01": "CS01 tenor",
            "exposure": "DV01 exposure",
        }
        for key, text in headings.items():
            self.result_tree.heading(key, text=text)
            self.result_tree.column(key, width=150, stretch=True)
        self.result_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.summary_var = tk.StringVar(value="No results yet")
        ttk.Label(frame, textvariable=self.summary_var).pack(anchor=tk.W, padx=10, pady=(0, 10))

    def refresh_results(self) -> None:
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)
        results = self.db.get_results()
        if not results:
            self.summary_var.set("No results available")
            return

        exposures = [result.dv01_exposure for result in results]
        spread = max(exposures) - min(exposures) if len(exposures) > 1 else 0.0
        average_exposure = sum(exposures) / len(exposures) if exposures else 0.0

        buckets = {bucket.bucket_key: bucket for bucket in self.db.get_buckets()}
        for result in results:
            bucket = buckets.get(result.bucket_key)
            bucket_label = result.bucket_key
            if bucket:
                bucket_label = f"{bucket.currency} / {bucket.time_horizon}y"
            self.result_tree.insert(
                "",
                tk.END,
                values=(
                    bucket_label,
                    f"{result.amount:.2f}",
                    f"{result.dv01_tenor:.2f}",
                    f"{result.bei01_tenor:.2f}",
                    f"{result.cs01_tenor:.2f}",
                    f"{result.dv01_exposure:.2f}",
                ),
            )

        self.summary_var.set(
            f"Exposure spread: {spread:.2f}; average exposure: {average_exposure:.2f}"
        )


if __name__ == "__main__":
    app = MoneyAllocApp()
    app.mainloop()

