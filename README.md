# Money Allocation Manager

A desktop application written in Python that helps you design and maintain a multi-level money allocation plan.  
It stores your allocations in a local SQLite database (`allocations.db`) and provides a convenient tree-based editor for creating, updating and removing buckets.

## Features

- Visualise your allocation hierarchy in a multi-column tree view.
- Create, edit and delete buckets with arbitrary nesting depth.
- Track both the share relative to the parent bucket and the cumulative share of the overall plan.
- Record the current monetary value for every allocation and update it as prices move.
- Mark buckets as *included* or *excluded* from the aggregated roll-up percentages.
- Attach notes to every allocation for additional context.
- Categorise allocations by time horizon and inherit that classification down the hierarchy.
- Generate distribution recommendations for new deposits or rebalancing, including invest/divest guidance based on a tolerance you choose.
- Import a comprehensive sample dataset or replace your data from a CSV export.
- Export the current database contents to CSV for backups or further processing.
- Keep an audit trail of saved distributions and review them at any time.

## Getting started

The application only requires the Python standard library (Tkinter is bundled with CPython on all major platforms).

1. Ensure you are using Python 3.11 or later.
2. Install the project in editable mode or simply run the entry module directly:

```bash
python -m moneyalloc_app
```

Alternatively you can use the helper script:

```bash
python main.py
```

On first launch an empty database is created next to the Python modules. Use **File → Import sample data** to load a detailed example hierarchy inspired by the plan provided in the task description.

## Working with the UI

- **Add root** creates a new top-level allocation that counts directly towards the global total.
- **Add child** creates a nested allocation under the currently selected bucket.
- **Edit** opens the selected bucket for changes. Saving updates the database immediately.
- **Delete** removes the selected bucket and all of its descendants.
- **Expand all / Collapse all** control the visibility of the hierarchy tree.
- The form on the right displays the details of the selection and exposes fields when you are adding or editing items.
- Update the **Current value** field whenever the value of an allocation changes (for example after a price movement).
- Use the **Instrument** field on leaf allocations to label positions that should be aggregated when rebalancing.
- Assign a **Time horizon** to parents or leaves using the `number + unit` format (for example `1Y`, `3M`, `6W` or `10D`). Empty children inherit the value from the closest ancestor, which can later be used to scope distributions.
- Switch between the **Distribute funds** and **Distribution history** tabs in the main window to work with recommendations and review previous plans.

The *Children share* label helps you verify that the percentages of the immediate children sum up correctly for the selected parent.

## Distributing money

Use the **Distribute funds** tab in the main window to enter the amount you would like to allocate and the maximum deviation (in percentage points) you are willing to tolerate. Optionally select a time horizon to recalculate the target percentages using only leaves that match that classification. The planner calculates the target value for every included allocation, highlights which buckets need investment or divestment, and allows you to save the plan to the database. When a calculation requires market assumptions the tab reveals the **Risk inputs** editor so you can supply the necessary yields and tenors without leaving the main window.

Saved plans can be reviewed or deleted from the **Distribution history** tab. The history view shows the recorded totals, the tolerance that was used and the recommended actions for each allocation.

## CSV import/export format

Exports contain the following columns:

| Column | Description |
| ------ | ----------- |
| `id` | Unique identifier of the allocation. |
| `parent_id` | Identifier of the parent allocation (empty for top-level rows). |
| `name` | Display name of the bucket. |
| `currency` | Optional currency label. |
| `instrument` | Optional instrument label used for aggregation in distribution plans. |
| `time_horizon` | Optional textual descriptor (for example *Short term*, *Long term*). |
| `target_percent` | Share of the parent bucket expressed as a percentage. |
| `include_in_rollup` | `1` if the allocation contributes to the overall totals, otherwise `0`. |
| `current_value` | Tracked monetary value of the allocation. |
| `notes` | Free-form description or comments. |
| `sort_order` | Integer describing the order of siblings. |

When importing from CSV you must keep these columns (you can edit the values). Older exports that do not yet contain the `time_horizon` column are still supported; empty values are treated as "no classification".
The application clears the current database before inserting the imported rows.

## Database location

The database file `allocations.db` lives inside the `moneyalloc_app` package directory by default. You can back it up or version it as needed. Deleting the file will reset the app.

## Development notes

- The project intentionally avoids third-party dependencies to ease distribution.
- The default Tkinter theme is switched to `clam` when available to provide a modern appearance.
- Sample data is declared programmatically in `moneyalloc_app/sample_data.py` and can be used as a template for further customisation.

## Risk optimisation internals

The planner applies a deterministic risk allocator implemented in [`moneyalloc_app/risk_optimizer.py`](moneyalloc_app/risk_optimizer.py). The behaviour can be summarised as follows:

- `_tenors_for_bucket` filters the sleeves that can serve a bucket by insisting that their tenor does not exceed the bucket horizon and that the tenor was either supplied for that bucket or for an earlier (shorter) bucket.
- `run_risk_equal_optimization` walks the buckets from the shortest horizon to the longest, builds a linear system that enforces the bucket minima, balances DV01/BEI01/CS01 exposure across the entire portfolio, and keeps currencies level whenever the same sleeve-tenor combination is investable in multiple regions.

When you run a distribution, the application records these details in the risk summary panel so it is clear how the global risk balancing and currency constraints shape the recommendation.
