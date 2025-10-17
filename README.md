# Moneyalloc

Moneyalloc is a Tkinter-based desktop application that helps you build and balance investment allocations.

## Features

1. Build a hierarchical allocation tree of asset distributions.
2. Aggregate leaf allocations into time horizon / currency buckets.
3. Input tenor options for each risk group and total investment amount.
4. Calculate an allocation that balances DV01 exposure while respecting tenor constraints.
5. Store all user inputs and calculated outputs in a local SQLite database (`moneyalloc.db`).

## Getting Started

1. Ensure you have Python 3.10+ installed.
2. Install Tkinter if it is not bundled with your Python distribution.
3. Run the application:

```bash
python app.py
```

The application will create `moneyalloc.db` in the working directory to persist your allocations, bucket inputs, and results.

## Usage Workflow

1. **Distributions tab** – Build the allocation tree. Each leaf must include comma-separated currencies and a numeric time horizon. Press **Generate buckets** to compute aggregated buckets.
2. **Buckets tab** – Review buckets, input available tenors for each risk group (DV01, BEI01, CS01), and enter the total amount to invest. Save the entries and press **Calculate**.
3. **Results tab** – View the calculated amounts, chosen tenors, and DV01 exposures. The application attempts to keep DV01 exposures as even as possible while respecting bucket constraints. Other risk group tenors are evenly derived from the DV01 tenor depending on how many risk groups are active.

All tables and inputs are persisted automatically in the SQLite database, allowing you to close and reopen the application without losing data.
