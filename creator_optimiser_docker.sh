#!/bin/bash
set -e  # exit on any error
LOG_FILE="$PWD/script.log"
exec > >(tee -ai "$LOG_FILE") 2>&1

echo "[INFO] Logging to $LOG_FILE"
# ------------------ Parse flags ------------------
NO_OPT=false

for arg in "$@"; do
    case $arg in
        --no-opt)
            NO_OPT=true
            shift
            ;;
    esac
done


# ------------------ 1. Activate conda environment ------------------
# Replace 'base' with your actual environment name
#echo "[INFO] Activating conda environment 'base'..."
#source "$(conda info --base)/etc/profile.d/conda.sh"
#conda activate base
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# ------------------ 2. Determine next run_* folder ------------------
BASE="run_"
if ls ${BASE}* &> /dev/null; then
    MAX=$(ls -d ${BASE}* | sed "s/${BASE}//" | sort -n | tail -1)
    NEXT=$((MAX + 1))
else
    NEXT=1
fi
RUN_FOLDER="${BASE}${NEXT}"
echo "[INFO] Next run folder: ${RUN_FOLDER}"

# ------------------ 3. Update OUTPUT_DIR in 28_Li_Na_doped.py ------------------
SCRIPT1="$SCRIPT_DIR/28_Li_Na_doped.py"
# Backup original just in case
cp "$SCRIPT1" "${SCRIPT1}.bak"

# Update OUTPUT_FOLDER to new run folder
sed -i "s|^OUTPUT_DIR *=.*|OUTPUT_DIR = \"./${RUN_FOLDER}\"|" "$SCRIPT1"
echo "[INFO] OUTPUT_DIR in $SCRIPT1 set to ./${RUN_FOLDER}"
sed -i "s|^OUTPUT_FOLDER *=.*|OUTPUT_FOLDER = \"./${RUN_FOLDER}\"|" "$SCRIPT1"
echo "[INFO] OUTPUT_FOLDER in $SCRIPT1 set to ./${RUN_FOLDER}"
# ------------------ 4. First run of 23 to generate available configs ------------------
python3 "$SCRIPT1"

# ------------------ 5. Run 26_site_distance_selector.py ------------------
SCRIPT2="$SCRIPT_DIR/26_site_distance_selector.py"
AVAILABLE_CONFIGS="${RUN_FOLDER}/available_configs.txt"
SELECTED_CONFIGS="${RUN_FOLDER}/selected_configs.txt"

echo "[INFO] Selecting configurations..."
python3 "$SCRIPT2" "$AVAILABLE_CONFIGS" --out "$SELECTED_CONFIGS"

if [ -f "$SELECTED_CONFIGS" ]; then
    echo "[INFO] selected_configs.txt successfully generated in ${RUN_FOLDER}/"
else
    echo "[ERROR] selected_configs.txt not found. Exiting."
    exit 1
fi

# ------------------ 6. Second run of 23 to generate all configurations ------------------
echo "[INFO] Generating all configurations for selected configs..."
python3 "$SCRIPT1"

echo "[INFO] Workflow completed. All outputs are in ${RUN_FOLDER}/"
# ----------------------------------------------------------------------

if [ "$NO_OPT" = true ]; then
    echo "[INFO] --no-opt flag detected. Skipping optimisation completely."
    exit 0
fi

echo "[INFO] Proceeding with optimisation..."


# ------------------ 7. Relax each folder inside the run folder (sequential) ------------------
SCRIPT3="$SCRIPT_DIR/25_orb_v3_multi_folder_relax.py"

echo "[INFO] Starting relaxation for all folders inside ${RUN_FOLDER}/"

cd "${RUN_FOLDER}"  # move into run_X

# Loop through all entries and run relax script on directories only
for ITEM in *; do
    if [ -d "$ITEM" ]; then
        echo "[INFO] Relaxing folder: $ITEM ..."
        python3 "$SCRIPT3" "$ITEM"
        echo "[INFO] Completed relaxation for: $ITEM"
    fi
done
touch optimization_done
cd ..

echo "[INFO] All relaxations completed."
