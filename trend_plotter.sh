#!/usr/bin/env bash
echo "[INFO] Activating conda environment 'base'..."
source "$(conda info --base)/etc/profile.d/conda.sh"

#!/usr/bin/env bash

echo "=== Processing run_* folders ==="

for dir in run_*; do
    if [ -d "$dir" ]; then
        echo ""
        echo ">>> Checking folder: $dir"

        csv_file=$(find "$dir" -maxdepth 1 -type f -name "energy_summary.csv" | head -n 1)

        if [ -z "$csv_file" ]; then
            echo "WARNING: No CSV file found in $dir — skipping."
            continue
        fi

        echo "Found CSV: $csv_file"
        echo "Running Python processing..."

python3 <<EOF
import csv
import matplotlib.pyplot as plt
import numpy as np
import os

csv_path = "$csv_file"
folder = os.path.dirname(csv_path)

# ---- Read CSV while handling duplicate headers ----
with open(csv_path, "r") as f:
    reader = csv.reader(f)
    raw_headers = next(reader)

    headers = []
    counts = {}

    # rename duplicates: Dist, Dist -> Dist_1, Dist_2
    for h in raw_headers:
        if h not in counts:
            counts[h] = 1
            headers.append(h)
        else:
            counts[h] += 1
            new_name = f"{h}_{counts[h]}"
            headers.append(new_name)

    rows = []
    for line in reader:
        row = {}
        for h, v in zip(headers, line):
            row[h] = v
        rows.append(row)

# ---- Filter only MIN rows ----
rows_min = [r for r in rows if r.get("Type") == "MIN"]

if not rows_min:
    print(f"No MIN rows in {csv_path}, skipping.")
    exit(0)

# ---- Find ALL distance columns (including duplicates) ----
dist_cols = [h for h in headers if "dist" in h.lower()]

if not dist_cols:
    print(f"No distance columns in {csv_path}, skipping.")
    exit(0)

print("Distance columns:", dist_cols)

# ---- Create output folder ----
out_dir = os.path.join(folder, "plots")
os.makedirs(out_dir, exist_ok=True)

# ---- Plot for each (including duplicates) ----
for col in dist_cols:
    x_vals, y_vals = [], []

    for r in rows_min:
        try:
            x_vals.append(float(r[col]))
            y_vals.append(float(r["Energy"]))
        except:
            continue

    if len(x_vals) < 2:
        print(f"Not enough numeric data for {col}, skipping.")
        continue

    x = np.array(x_vals)
    y = np.array(y_vals)

    # linear regression
    m, b = np.polyfit(x, y, 1)
    y_fit = m * x + b

    # ----- NICER PLOT -----
    plt.figure(figsize=(7, 5))
    plt.scatter(x, y, s=40, alpha=0.8)
    plt.plot(x, y_fit, linewidth=2)

    plt.xlabel(col, fontsize=12)
    plt.ylabel("Energy", fontsize=12)
    plt.title(f"{col} vs Energy (MIN only)", fontsize=14)
    plt.grid(True, linestyle="--", alpha=0.3)

    # regression equation text box
    eq = f"y = {m:.4f}x + {b:.4f}"
    plt.text(0.05, 0.95, eq, transform=plt.gca().transAxes,
             fontsize=10, verticalalignment='top',
             bbox=dict(boxstyle="round,pad=0.3", fc="white", alpha=0.7))

    plt.tight_layout()

    safe = col.replace("(", "").replace(")", "").replace(" ", "_")
    out_path = os.path.join(out_dir, f"scatter_{safe}.png")

    plt.savefig(out_path, dpi=300)
    plt.close()

    print(f"Saved: {out_path}")

print("Done:", csv_path)
EOF

    fi
done

echo ""
echo "=== All folders processed ==="
