#!/bin/bash

# Activate conda base
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate base

# Directory where THIS bash script and python scripts live
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Loop through MD_run_* directories where data lives
for folder in MD_run_*; do
    [ -d "$folder" ] || continue

    log_file="$folder/rdf_process.log"

    echo "========================================" | tee -a "$log_file"
    echo "[INFO] Processing $folder" | tee -a "$log_file"

    # Enter the MD directory so outputs go THERE
    cd "$folder" || continue

    # Find dump file locally
    dump_file=$(ls dump*900* 2>/dev/null | head -n 1)
    if [[ -z "$dump_file" ]]; then
        echo "[WARN] No dump file with 900 found" | tee -a rdf_process.log
        cd ..
        continue
    fi

    # Run RDF script (script elsewhere, data here)
    python "$SCRIPT_DIR/17_get_rdf_from_vmd.py" "$dump_file" \
        2>&1 | tee -a rdf_process.log

    # Ensure at least one RDF output exists
    dat_files=(*.dat)
    if [[ ${#dat_files[@]} -eq 0 || ! -f "${dat_files[0]}" ]]; then
        echo "[ERROR] No .dat RDF files found" | tee -a rdf_process.log
        cd ..
        continue
    fi

    echo "[INFO] Found RDF files: ${dat_files[*]}" | tee -a rdf_process.log

    # Run CN script on ALL pair RDF files, not just 1-1.dat
    python "$SCRIPT_DIR/18_get_CN_from_rdf.py" "${dat_files[@]}" \
        2>&1 | tee -a rdf_process.log

    # Return to parent directory
    cd ..
done
