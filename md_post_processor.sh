#!/bin/bash
# set -e intentionally omitted — per-folder errors are handled explicitly below


# Directory where THIS script (and Python files) live
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo "[INFO] Python scripts directory: $SCRIPT_DIR"

# Directory where we are running this script
RUN_DIR="$(pwd)"
echo "[INFO] Running script in: $RUN_DIR"
echo "[INFO] Looking for MD_run_* folders in: $RUN_DIR"

# Check if Python scripts exist
if [[ ! -f "$SCRIPT_DIR/12_plot_MSD_arrhenius.py" ]]; then
    echo "[ERROR] Cannot find 12_plot_MSD_arrhenius.py in $SCRIPT_DIR"
    exit 1
fi

if [[ ! -f "$SCRIPT_DIR/21_get_elastic_properties.py" ]]; then
    echo "[ERROR] Cannot find 21_get_elastic_properties.py in $SCRIPT_DIR"
    exit 1
fi

# Loop through folders
for folder in "$RUN_DIR"/MD_run_*; do

    # If the glob does not match anything, skip
    if [[ ! -d "$folder" ]]; then
        continue
    fi

    echo "[INFO] Processing folder: $folder"

    LOGFILE="$folder/analysis.log"
    echo "[INFO] Log file: $LOGFILE"

    # Run each script independently so a failure in one doesn't skip the other.
    # Errors are printed to terminal AND written to the log.
    FOLDER_OK=true

    echo "[INFO] Running 12_plot_MSD_arrhenius.py" | tee -a "$LOGFILE"
    if ! python "$SCRIPT_DIR/12_plot_MSD_arrhenius.py" "$folder" 2>&1 | tee -a "$LOGFILE"; then
        echo "[ERROR] 12_plot_MSD_arrhenius.py failed for $folder — continuing." | tee -a "$LOGFILE"
        FOLDER_OK=false
    fi

    echo "[INFO] Running 21_get_elastic_properties.py" | tee -a "$LOGFILE"
    if ! python "$SCRIPT_DIR/21_get_elastic_properties.py" "$folder" 2>&1 | tee -a "$LOGFILE"; then
        echo "[ERROR] 21_get_elastic_properties.py failed for $folder — continuing." | tee -a "$LOGFILE"
        FOLDER_OK=false
    fi

    if [[ "$FOLDER_OK" == true ]]; then
        echo "[INFO] Finished successfully: $folder"
    else
        echo "[WARNING] Finished with errors: $folder — check $LOGFILE"
    fi

done

echo "[DONE] All MD_run_* folders processed."
