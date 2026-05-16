#!/bin/bash
set -euo pipefail

#echo "[INFO] Activating conda environment 'base'..."
#source "$(conda info --base)/etc/profile.d/conda.sh"
#conda activate base

echo "[INFO] Starting scan for run_* folders..."

MAIN_DIR=$(pwd)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Check required files exist in the script's directory
for f in gnnp_driver.py in_LLZO 27_gen_data_file_element_list.py; do
    if [[ ! -f "$SCRIPT_DIR/$f" ]]; then
        echo "[ERROR] Required file '$f' not found in $SCRIPT_DIR"
        exit 1
    fi
done

for RUN_DIR in run_*; do
    [[ -d "$RUN_DIR" ]] || continue

    # require optimization_done inside the run dir
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

    # Find the last row whose Type column == GLOBAL_MIN
    eval "$(
        awk -F',' '
        BEGIN{folder=""; fname=""; energy="";}
        $3=="GLOBAL_MIN"{
            gsub(/^[ \t]+|[ \t]+$/, "", $2);
            folder=$2;
            fname=$(NF-1);
            energy=$(NF);
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

    echo "[INFO] GLOBAL_MIN entry from CSV:"
    echo "       Folder: $FOLDER_RAW"
    echo "       Filename: $FILENAME"
    echo "       Energy: $ENERGY"

    # Normalize folder path inside CSV
    if [[ "$FOLDER_RAW" == "$RUN_DIR/"* ]]; then
        SUBDIR_REL="${FOLDER_RAW#${RUN_DIR}/}"
    elif [[ "$FOLDER_RAW" == run_*/* ]]; then
        SUBDIR_REL="${FOLDER_RAW#run_*/}"
    else
        SUBDIR_REL="$FOLDER_RAW"
    fi

    # Build full CIF path
    CIF_FULL="$MAIN_DIR/$RUN_DIR/$SUBDIR_REL/$FILENAME"
    if [[ ! -f "$CIF_FULL" ]]; then
        echo "[ERROR] CIF file not found: $CIF_FULL"
        exit 1
    fi

    echo "[INFO] CIF identified: $CIF_FULL"

    # Create MD_run_*
    MD_DIR="MD_run_${RUN_NUM}"
    mkdir -p "$MD_DIR"
    echo "[INFO] Created $MD_DIR"

    # Copy CIF and support files
    CIF_BASENAME=$(basename "$CIF_FULL")
    cp "$CIF_FULL" "$MD_DIR/"
    cp "$SCRIPT_DIR/gnnp_driver.py" "$SCRIPT_DIR/in_LLZO" "$MD_DIR/"
    echo "[INFO] Copied CIF and support files to $MD_DIR"

    # Run Python converter
    echo "[INFO] Running data + element list generator..."
    (
        cd "$MD_DIR"
        python3 "$SCRIPT_DIR/27_gen_data_file_element_list.py" "$CIF_BASENAME"
    )
    echo "[SUCCESS] Generated lmp.data and element_list"

    # Check element_list
    if [[ ! -f "$MD_DIR/element_list" ]]; then
        echo "[ERROR] element_list not generated in $MD_DIR — aborting."
        exit 1
    fi

    ELEMENT_LIST=$(cat "$MD_DIR/element_list")
    read -r -a ELEMENT_ARRAY <<< "$ELEMENT_LIST"


    # Count occurrences of Li and Na
    LI_COUNT=0
    NA_COUNT=0
    for e in "${ELEMENT_ARRAY[@]}"; do
        [[ "$e" == "Li" ]] && ((LI_COUNT++))
        [[ "$e" == "Na" ]] && ((NA_COUNT++))
    done

    if (( LI_COUNT > 0 && NA_COUNT > 0 )); then
        echo "[ERROR] Both Li and Na present in element_list — only one carrier type allowed."
        exit 1
    fi

    # Determine carrier atom type
    CARRIER_TYPE=""
    CARRIER_NAME=""
    for i in "${!ELEMENT_ARRAY[@]}"; do
        if [[ "${ELEMENT_ARRAY[$i]}" == "Li" || "${ELEMENT_ARRAY[$i]}" == "Na" ]]; then
            CARRIER_TYPE=$((i + 1))   # LAMMPS 1-based
            CARRIER_NAME="${ELEMENT_ARRAY[$i]}"
            break
        fi
    done

    if [[ -z "$CARRIER_TYPE" ]]; then
        echo "[ERROR] Carrier (Li or Na) not found in element_list — cannot update group type."
        exit 1
    fi

    echo "[INFO] element_list = $ELEMENT_LIST"
    echo "[INFO] Carrier atom = $CARRIER_NAME, type = $CARRIER_TYPE"

    # Update ElemList in in_LLZO
    if grep -q '^variable ElemList string ' "$MD_DIR/in_LLZO"; then
        TMPFILE="$(mktemp)"
        awk -v el="$ELEMENT_LIST" '
            /^variable ElemList string /{
                print "variable ElemList string \"" el "\"";
                next
            }
            {print}
        ' "$MD_DIR/in_LLZO" > "$TMPFILE"
        mv "$TMPFILE" "$MD_DIR/in_LLZO"
        echo "[SUCCESS] Updated in_LLZO with new element list"
    else
        echo "[WARNING] in_LLZO did not contain a variable ElemList string line — leaving file unchanged."
    fi

    # Update group type1 in in_LLZO
    if grep -q '^group[[:space:]]\+type1[[:space:]]\+type[[:space:]]\+[0-9]\+' "$MD_DIR/in_LLZO"; then
        TMPFILE="$(mktemp)"
        awk -v carrier_type="$CARRIER_TYPE" '
            /^group[[:space:]]+type1[[:space:]]+type[[:space:]]+[0-9]+/{
                print "group       type1 type " carrier_type
                next
            }
            {print}
        ' "$MD_DIR/in_LLZO" > "$TMPFILE"
        mv "$TMPFILE" "$MD_DIR/in_LLZO"
        echo "[SUCCESS] Updated group type1 to carrier atom type ($CARRIER_NAME)"
    else
        echo "[WARNING] group type1 line not found in in_LLZO — no change made."
    fi

done

# Prompt user before MD runs
echo -e "\n[WARNING] About to start MD runs for all MD_run_* folders."
RESP=""
read -t 10 -p "Do you want to proceed with the MD run? (yes/no) [default: yes]: " RESP || true
if [[ -z "${RESP}" ]]; then
    RESP="yes"
fi

if [[ "$RESP" =~ ^[Nn][Oo]$ ]]; then
    echo "[INFO] User chose NO. Exiting script."
    exit 0
else
    echo "[INFO] Proceeding with MD runs..."
fi

echo "[INFO] Starting sequential LAMMPS runs in Docker for all MD_run_* folders..."

for MD_DIR in MD_run_*; do
    [[ -d "$MD_DIR" ]] || continue
    echo -e "\n[INFO] Running LAMMPS for $MD_DIR"
    (
        cd "$MD_DIR"
        lmp -in in_LLZO
    )
    echo "[SUCCESS] Completed LAMMPS run for $MD_DIR"
done

echo "[INFO] All MD_run_* folders processed."
echo -e "\n[ALL DONE]"
