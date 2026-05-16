#!/bin/bash
set -e

echo "[INFO] Activating conda environment 'base'..."
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate base

echo "[INFO] Starting deep scan inside run_* folders..."

shopt -s nullglob
RUN_FOLDERS=(run_*)
shopt -u nullglob

if [ ${#RUN_FOLDERS[@]} -eq 0 ]; then
    echo "[ERROR] No run_* folders found. Exiting."
    exit 1
fi

for RUN in "${RUN_FOLDERS[@]}"; do
    echo "[INFO] Inspecting $RUN ..."

    if [ ! -f "$RUN/optimization_done" ]; then
        echo "[WARNING] Skipping $RUN — Optimization not complete."
        continue
    fi

    SUMMARY_CSV="$RUN/energy_summary.csv"
    rm -f "$SUMMARY_CSV"
    header_written=0

    shopt -s nullglob
    SUBFOLDERS=("$RUN"/*)
    shopt -u nullglob

    for SUB in "${SUBFOLDERS[@]}"; do
        [ -d "$SUB" ] || continue

        ENERGY_FILE="$SUB/energies.txt"
        PAIR_FILE="$SUB/pair_distances.csv"

        if [ ! -f "$ENERGY_FILE" ]; then
            echo "[ERROR] Missing energies.txt in $SUB. Skipping."
            continue
        fi
        if [ ! -f "$PAIR_FILE" ]; then
            echo "[ERROR] Missing pair_distances.csv in $SUB. Skipping."
            continue
        fi

        echo "[INFO] Processing $SUB"

        cp "$ENERGY_FILE" "$SUB/energies.txt.bak"
        cp "$PAIR_FILE" "$SUB/pair_distances.csv.bak"

        # ---------------- PYTHON BLOCK: update CSV + local min/max + header ----------------
        python3 <<EOF
import os, re, pandas as pd

energy_file = "$ENERGY_FILE"
pair_file = "$PAIR_FILE"
summary_csv = "$SUMMARY_CSV"
run = "$RUN"
folder = "$SUB"

# read energies.txt
names = []
energies = []
with open(energy_file) as f:
    for line in f:
        n,e = line.split()
        names.append(n)
        energies.append(float(e))

df = pd.read_csv(pair_file)

if len(df) != len(names):
    print("[ERROR] Row mismatch in", folder)
    exit(1)

df["Filename"] = names
df["Energy"] = energies

df.to_csv(pair_file, index=False)

# find local min/max
min_idx = energies.index(min(energies))
max_idx = energies.index(max(energies))

# clean header
def clean(c):
    if c in ["Filename","Energy"]:
        return c
    return re.sub(r"[0-9]+","",c)

clean_cols = [clean(c) for c in df.columns]
df.columns = clean_cols

# write header once
if $header_written == 0:
    with open(summary_csv, "w") as S:
        S.write("Run,Folder,Type," + ",".join(clean_cols) + "\n")
EOF

        header_written=1

        # -------- append MIN & MAX rows --------
        python3 <<EOF
import pandas as pd, re

pair_file = "$PAIR_FILE"
energy_file = "$ENERGY_FILE"
summary_csv = "$SUMMARY_CSV"
run = "$RUN"
folder = "$SUB"

names = []
energies = []
with open(energy_file) as f:
    for line in f:
        n,e = line.split()
        names.append(n)
        energies.append(float(e))

df = pd.read_csv(pair_file)

# clean header
def clean(c):
    if c in ["Filename","Energy"]:
        return c
    return re.sub(r"[0-9]+","",c)

df.columns = [clean(c) for c in df.columns]

min_idx = energies.index(min(energies))
max_idx = energies.index(max(energies))

with open(summary_csv, "a") as S:
    S.write(f"{run},{folder},MIN," + ",".join(map(str, df.iloc[min_idx].tolist())) + "\n")
    S.write(f"{run},{folder},MAX," + ",".join(map(str, df.iloc[max_idx].tolist())) + "\n")
EOF

    done

    # =====================================================
    # GLOBAL MIN / MAX FOR THIS RUN
    # =====================================================
    echo "[INFO] Computing GLOBAL MIN/MAX for $RUN"

    python3 <<EOF
import pandas as pd

summary_csv = "$SUMMARY_CSV"

df = pd.read_csv(summary_csv)
df = df.dropna(how="all")

# energy column is always present
gmin = df.loc[df["Energy"].idxmin()]
gmax = df.loc[df["Energy"].idxmax()]

min_row = ["GLOBAL_MIN", gmin["Folder"], "GLOBAL_MIN"] + gmin.iloc[3:].tolist()
max_row = ["GLOBAL_MAX", gmax["Folder"], "GLOBAL_MAX"] + gmax.iloc[3:].tolist()

with open(summary_csv, "a") as S:
    S.write(",".join(map(str,min_row)) + "\n")
    S.write(",".join(map(str,max_row)) + "\n")

EOF

    echo "[INFO] Finished $RUN → $SUMMARY_CSV"

done

echo "[INFO] ALL RUNS COMPLETE."
