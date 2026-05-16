#!/bin/bash
set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------
# md_runner.sh — merged plain + docker runner
#
# Usage:
#   ./md_runner.sh              # lmp called directly (plain env)
#   ./md_runner.sh --docker     # same, but signals script is
#                               # already running inside a container
#
# The --docker flag does NOT wrap lmp in `docker run` — it is a
# signal that this script was launched inside the container via
# e.g. `docker run ... bash md_runner.sh --docker`. The lmp
# invocation itself is identical in both modes.
#
# All setup logic (CIF selection, element list, in_LLZO patching,
# carrier detection) is always run and is identical for both modes.
# ---------------------------------------------------------------

USE_DOCKER=false
for arg in "$@"; do
    case $arg in
        --docker) USE_DOCKER=true; shift ;;
    esac
done

if [[ "$USE_DOCKER" == true ]]; then
    echo "[INFO] Mode: Docker (script running inside container)"
else
    echo "[INFO] Mode: Plain"
fi

MAIN_DIR=$(pwd)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ------------------ Preflight checks ------------------
for f in gnnp_driver.py in_LLZO 27_gen_data_file_element_list.py; do
    if [[ ! -f "$SCRIPT_DIR/$f" ]]; then
        echo "[ERROR] Required file '$f' not found in $SCRIPT_DIR"
        exit 1
    fi
done

echo "[INFO] Starting scan for run_* folders..."

# ---------------------------------------------------------------
# Phase 1: For each run_*, pick the GLOBAL_MIN CIF and set up
#          its MD_run_* folder (data file, element list, in_LLZO)
# ---------------------------------------------------------------
for RUN_DIR in run_*; do
    [[ -d "$RUN_DIR" ]] || continue

    if [[ ! -f "$RUN_DIR/optimization_done" ]]; then
        echo "[INFO] Skipping $RUN_DIR — optimization_done not present."
        continue
    fi

    RUN_NUM=${RUN_DIR#run_}
    echo -e "\n[INFO] Processing $RUN_DIR (run number = $RUN_NUM)"

    ESUM_CSV="$RUN_DIR/energy_summary.csv"
    if [[ ! -f "$ESUM_CSV" ]]; then
        echo "[WARNING] No energy_summary.csv in $RUN_DIR, skipping."
        continue
    fi

    # Parse GLOBAL_MIN row from CSV
    eval "$(
        awk -F',' '
        BEGIN{folder=""; fname=""; energy="";}
        $3=="GLOBAL_MIN"{
            gsub(/^[ \t]+|[ \t]+$/, "", $2);
            folder=$2; fname=$(NF-1); energy=$(NF);
            gsub(/^"|"$/, "", folder);
            gsub(/^"|"$/, "", fname);
            gsub(/^"|"$/, "", energy);
            gsub(/\\/,"\\\\",folder); gsub(/"/,"\\\"",folder);
            gsub(/\\/,"\\\\",fname);  gsub(/"/,"\\\"",fname);
            gsub(/\\/,"\\\\",energy); gsub(/"/,"\\\"",energy);
        }
        END{
            if(folder!=""){
                printf "FOLDER_RAW=\"%s\"; FILENAME=\"%s\"; ENERGY=\"%s\";\n", folder, fname, energy;
            }
        }' "$ESUM_CSV"
    )"

    if [[ -z "${FOLDER_RAW-}" || -z "${FILENAME-}" ]]; then
        echo "[WARNING] No GLOBAL_MIN row found in $ESUM_CSV for $RUN_DIR, skipping."
        continue
    fi

    echo "[INFO] GLOBAL_MIN entry:"
    echo "       Folder:   $FOLDER_RAW"
    echo "       Filename: $FILENAME"
    echo "       Energy:   $ENERGY"

    # Normalize folder path
    if [[ "$FOLDER_RAW" == "$RUN_DIR/"* ]]; then
        SUBDIR_REL="${FOLDER_RAW#${RUN_DIR}/}"
    elif [[ "$FOLDER_RAW" == run_*/* ]]; then
        SUBDIR_REL="${FOLDER_RAW#run_*/}"
    else
        SUBDIR_REL="$FOLDER_RAW"
    fi

    CIF_FULL="$MAIN_DIR/$RUN_DIR/$SUBDIR_REL/$FILENAME"
    if [[ ! -f "$CIF_FULL" ]]; then
        echo "[ERROR] CIF file not found: $CIF_FULL"
        exit 1
    fi
    echo "[INFO] CIF identified: $CIF_FULL"

    # Create and populate MD_run_*
    MD_DIR="MD_run_${RUN_NUM}"
    mkdir -p "$MD_DIR"
    echo "[INFO] Created $MD_DIR"

    CIF_BASENAME=$(basename "$CIF_FULL")
    cp "$CIF_FULL" "$MD_DIR/"
    cp "$SCRIPT_DIR/gnnp_driver.py" "$SCRIPT_DIR/in_LLZO" "$MD_DIR/"
    echo "[INFO] Copied CIF and support files to $MD_DIR"

    # Generate lmp.data and element_list
    echo "[INFO] Running data + element list generator..."
    (
        cd "$MD_DIR"
        python3 "$SCRIPT_DIR/27_gen_data_file_element_list.py" "$CIF_BASENAME"
    )
    echo "[SUCCESS] Generated lmp.data and element_list"

    if [[ ! -f "$MD_DIR/element_list" ]]; then
        echo "[ERROR] element_list not generated in $MD_DIR — aborting."
        exit 1
    fi

    ELEMENT_LIST=$(cat "$MD_DIR/element_list")
    read -r -a ELEMENT_ARRAY <<< "$ELEMENT_LIST"
    echo "[INFO] element_list = $ELEMENT_LIST"

    # ------------------ Carrier detection ------------------
    # Exactly one of Li or Na must be present — not both.
    LI_COUNT=0
    NA_COUNT=0
    for e in "${ELEMENT_ARRAY[@]}"; do
        [[ "$e" == "Li" ]] && (( LI_COUNT++ )) || true
        [[ "$e" == "Na" ]] && (( NA_COUNT++ )) || true
    done

    if (( LI_COUNT > 0 && NA_COUNT > 0 )); then
        echo "[ERROR] Both Li and Na found in element_list — only one carrier type allowed."
        exit 1
    fi

    CARRIER_TYPE=""
    CARRIER_NAME=""
    for i in "${!ELEMENT_ARRAY[@]}"; do
        if [[ "${ELEMENT_ARRAY[$i]}" == "Li" || "${ELEMENT_ARRAY[$i]}" == "Na" ]]; then
            CARRIER_TYPE=$(( i + 1 ))   # LAMMPS atom types are 1-based
            CARRIER_NAME="${ELEMENT_ARRAY[$i]}"
            break
        fi
    done

    if [[ -z "$CARRIER_TYPE" ]]; then
        echo "[ERROR] No carrier ion (Li or Na) in element_list — cannot set group type."
        exit 1
    fi
    echo "[INFO] Carrier: $CARRIER_NAME  (LAMMPS atom type $CARRIER_TYPE)"

    # ------------------ Patch in_LLZO ------------------
    # 1. ElemList variable
    if grep -q '^variable ElemList string ' "$MD_DIR/in_LLZO"; then
        TMPFILE="$(mktemp)"
        awk -v el="$ELEMENT_LIST" '
            /^variable ElemList string /{ print "variable ElemList string \"" el "\""; next }
            { print }
        ' "$MD_DIR/in_LLZO" > "$TMPFILE"
        mv "$TMPFILE" "$MD_DIR/in_LLZO"
        echo "[SUCCESS] Updated ElemList in in_LLZO"
    else
        echo "[WARNING] No 'variable ElemList string' line in in_LLZO — leaving unchanged."
    fi

    # 2. group type1 — must point at the carrier atom type
    if grep -qE '^group[[:space:]]+type1[[:space:]]+type[[:space:]]+[0-9]+' "$MD_DIR/in_LLZO"; then
        TMPFILE="$(mktemp)"
        awk -v ct="$CARRIER_TYPE" '
            /^group[[:space:]]+type1[[:space:]]+type[[:space:]]+[0-9]+/{ print "group       type1 type " ct; next }
            { print }
        ' "$MD_DIR/in_LLZO" > "$TMPFILE"
        mv "$TMPFILE" "$MD_DIR/in_LLZO"
        echo "[SUCCESS] Updated group type1 → type $CARRIER_TYPE ($CARRIER_NAME)"
    else
        echo "[WARNING] No 'group type1 type N' line in in_LLZO — leaving unchanged."
    fi

done

# ---------------------------------------------------------------
# Phase 2: Confirm with user then run LAMMPS
# ---------------------------------------------------------------
echo -e "\n[WARNING] About to start MD runs for all MD_run_* folders."
RESP=""
read -t 10 -p "Do you want to proceed? (yes/no) [default: yes]: " RESP || true
[[ -z "${RESP}" ]] && RESP="yes"

if [[ "$RESP" =~ ^[Nn][Oo]$ ]]; then
    echo "[INFO] User chose NO. Exiting."
    exit 0
fi

echo "[INFO] Proceeding with MD runs..."

for MD_DIR in MD_run_*; do
    [[ -d "$MD_DIR" ]] || continue
    echo -e "\n[INFO] Running LAMMPS for $MD_DIR"
    (
        cd "$MD_DIR"
        lmp -in in_LLZO
    )
    echo "[SUCCESS] Completed LAMMPS run for $MD_DIR"
done

echo -e "\n[ALL DONE]"
