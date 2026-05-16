#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install it with: pip install pyyaml"
    ) from exc


ROOT = Path(__file__).resolve().parent
WORK_DIR = ROOT / ".pipeline_runner"
SCRIPT_WORK_DIR = WORK_DIR / "scripts"
LOG_FILE = ROOT / "pipeline.log"
RUN_ROOT = ROOT

SCRIPT_FILES = [
    "12_plot_MSD_arrhenius.py",
    "17_get_rdf_from_vmd.py",
    "18_get_CN_from_rdf.py",
    "21_get_elastic_properties.py",
    "25_orb_v3_multi_folder_relax.py",
    "26_site_distance_selector.py",
    "27_gen_data_file_element_list.py",
    "28_Li_Na_doped.py",
    "creator_optimiser_docker.sh",
    "csv_editor__energy_comparator.sh",
    "get_rdf.sh",
    "md_post_processor.sh",
    "md_runner.sh",
    "trend_plotter.sh",
    "gnnp_driver.py",
    "in_LLZO",
]


def log(message):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {message}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def resolve_path(path, base=ROOT):
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def load_config(path):
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if not isinstance(cfg, dict):
        raise ValueError("input.yaml must contain a mapping at the top level")
    return cfg


def configure_runtime(cfg):
    global LOG_FILE, RUN_ROOT
    RUN_ROOT = resolve_path(cfg.get("output_dir", "."), ROOT)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    LOG_FILE = RUN_ROOT / "pipeline.log"
    return RUN_ROOT


def validate_config(cfg):
    md_temps = {int(t) for t in cfg.get("md_temperatures", [])}
    rdf_temps = cfg.get("rdf_temperatures", cfg.get("md_temperatures", []))
    rdf_temps = [int(t) for t in (rdf_temps or [])]
    if cfg.get("run_rdf", True) and not rdf_temps:
        raise ValueError("At least one RDF temperature is required when RDF is enabled")
    missing = sorted(set(rdf_temps) - md_temps)
    if missing:
        raise ValueError(
            "RDF temperatures must be selected from MD temperatures. "
            f"Invalid RDF temperatures: {missing}; MD temperatures: {sorted(md_temps)}"
        )
    pairs = cfg.get("rdf_pairs", "all")
    if pairs != "all":
        invalid_pairs = []
        for pair in pairs:
            parts = str(pair).split("-")
            if len(parts) != 2 or not all(part.isalpha() for part in parts):
                invalid_pairs.append(pair)
        if invalid_pairs:
            raise ValueError(
                "RDF pairs must use element names like Li-Li or Li-O, not type numbers. "
                f"Invalid pairs: {invalid_pairs}"
            )
    cfg["rdf_temperatures"] = rdf_temps


def py_repr(value):
    if value is None:
        return "None"
    return repr(value)


def shell_quote(value):
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def replace_assignment(text, name, value):
    pattern = rf"^{name}\s*=.*$"
    repl = f"{name} = {value}"
    new_text, count = re.subn(pattern, repl, text, flags=re.MULTILINE)
    if count == 0:
        raise RuntimeError(f"Could not find assignment for {name}")
    return new_text


def copy_scripts():
    SCRIPT_WORK_DIR.mkdir(parents=True, exist_ok=True)
    for name in SCRIPT_FILES:
        src = ROOT / name
        if not src.exists():
            raise FileNotFoundError(f"Required file missing: {src}")
        dst = SCRIPT_WORK_DIR / name
        shutil.copy2(src, dst)
        if dst.suffix == ".sh":
            dst.chmod(dst.stat().st_mode | 0o111)


def patch_doping_script(cfg):
    path = SCRIPT_WORK_DIR / "28_Li_Na_doped.py"
    text = path.read_text(encoding="utf-8")
    filters = cfg.get("distance_filters", {}) or {}

    text = replace_assignment(text, "INPUT_CIF", py_repr(str(resolve_path(cfg["cif"], ROOT))))
    text = replace_assignment(text, "SUPERCELL", py_repr(tuple(cfg.get("supercell", [1, 1, 1]))))
    text = replace_assignment(text, "MAX_FILES_PER_FOLDER", py_repr(int(cfg.get("max_files_per_folder", 1000))))
    text = replace_assignment(text, "DOP_DOP_MIN", py_repr(filters.get("dop_dop_min")))
    text = replace_assignment(text, "DOP_DOP_MAX", py_repr(filters.get("dop_dop_max")))
    text = replace_assignment(text, "DOP_ION_MIN", py_repr(filters.get("dop_ion_min")))
    text = replace_assignment(text, "DOP_ION_MAX", py_repr(filters.get("dop_ion_max")))
    text = replace_assignment(text, "ION_ION_MIN", py_repr(filters.get("ion_ion_min")))
    text = replace_assignment(text, "ION_ION_MAX", py_repr(filters.get("ion_ion_max")))

    dopants = cfg.get("dopants") or []
    if not dopants:
        raise ValueError("At least one dopant entry is required")
    text = re.sub(
        r"^DOPANTS\s*=\s*\[.*?\n\]",
        "DOPANTS = " + py_repr(dopants),
        text,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )
    path.write_text(text, encoding="utf-8")


def patch_msd_script(cfg):
    path = SCRIPT_WORK_DIR / "12_plot_MSD_arrhenius.py"
    text = path.read_text(encoding="utf-8")
    text = replace_assignment(text, "X_START", py_repr(cfg.get("msd_fit_start", 100)))
    text = replace_assignment(text, "X_END", py_repr(cfg.get("msd_fit_end", 200)))
    text = replace_assignment(text, "T_REF", py_repr(cfg.get("conductivity_t_ref", 300)))
    text = replace_assignment(text, "CARRIER_SPECIES", py_repr(cfg.get("carrier_species")))
    path.write_text(text, encoding="utf-8")


def patch_creator_script(cfg):
    path = SCRIPT_WORK_DIR / "creator_optimiser_docker.sh"
    text = path.read_text(encoding="utf-8")
    model = int(cfg.get("relax_model", 1))
    text = text.replace(
        'python3 "$SCRIPT3" "$ITEM"',
        f'python3 "$SCRIPT3" "$ITEM" --model {model}',
    )
    path.write_text(text, encoding="utf-8")


def patch_post_processor(cfg):
    path = SCRIPT_WORK_DIR / "md_post_processor.sh"
    text = path.read_text(encoding="utf-8")
    if not cfg.get("run_msd_arrhenius", True):
        text = re.sub(
            r'\n\s*echo "\[INFO\] Running 12_plot_MSD_arrhenius\.py".*?FOLDER_OK=false\n\s*fi\n',
            "\n",
            text,
            count=1,
            flags=re.DOTALL,
        )
    if not cfg.get("run_elastic", True):
        text = re.sub(
            r'\n\s*echo "\[INFO\] Running 21_get_elastic_properties\.py".*?FOLDER_OK=false\n\s*fi\n',
            "\n",
            text,
            count=1,
            flags=re.DOTALL,
        )
    path.write_text(text, encoding="utf-8")


def patch_rdf_script(cfg):
    path = SCRIPT_WORK_DIR / "get_rdf.sh"
    temps = cfg.get("rdf_temperatures", cfg.get("md_temperatures", [900])) or [900]
    pattern = cfg.get("md_dump_pattern", "dump*{T}*")
    pairs = cfg.get("rdf_pairs", "all")
    rmax = float(cfg.get("rdf_rmax", 10.0))
    dr = float(cfg.get("rdf_dr", 0.05))

    if pairs == "all":
        pair_expr = 'dat_files=(*.dat)'
    else:
        pair_specs = [str(p).strip() for p in pairs if str(p).strip()]
        pair_expr = f"""rdf_pair_specs=({" ".join(shell_quote(p) for p in pair_specs)})
            dat_files=()
            if [[ ! -f ../element_list ]]; then
                echo "[ERROR] element_list not found; cannot map element RDF pairs to LAMMPS types" | tee -a ../rdf_process.log
            else
                read -r -a element_array < ../element_list
                type_for_element() {{
                    local wanted="$1"
                    local idx
                    for idx in "${{!element_array[@]}}"; do
                        if [[ "${{element_array[$idx]}}" == "$wanted" ]]; then
                            echo $((idx + 1))
                            return 0
                        fi
                    done
                    return 1
                }}
                for spec in "${{rdf_pair_specs[@]}}"; do
                    left="${{spec%-*}}"
                    right="${{spec#*-}}"
                    t1="$(type_for_element "$left" || true)"
                    t2="$(type_for_element "$right" || true)"
                    if [[ -z "$t1" || -z "$t2" ]]; then
                        echo "[ERROR] RDF pair $spec cannot be mapped using element_list: ${{element_array[*]}}" | tee -a ../rdf_process.log
                        continue
                    fi
                    if [[ -f "${{t1}}-${{t2}}.dat" ]]; then
                        dat_files+=("${{t1}}-${{t2}}.dat")
                    elif [[ -f "${{t2}}-${{t1}}.dat" ]]; then
                        dat_files+=("${{t2}}-${{t1}}.dat")
                    else
                        echo "[ERROR] RDF file for $spec mapped to types $t1-$t2 was not found" | tee -a ../rdf_process.log
                    fi
                done
            fi"""

    temp_words = " ".join(str(t) for t in temps)
    text = f"""#!/bin/bash
set -u

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate base

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"

for folder in MD_run_*; do
    [ -d "$folder" ] || continue
    log_file="$folder/rdf_process.log"
    echo "========================================" | tee -a "$log_file"
    echo "[INFO] Processing $folder" | tee -a "$log_file"

    cd "$folder" || continue

    for T in {temp_words}; do
        pattern={shell_quote(pattern)}
        pattern="${{pattern//\\{{T\\}}/$T}}"
        candidate=$(ls $pattern 2>/dev/null | head -n 1 || true)
        if [[ -z "$candidate" ]]; then
            echo "[WARN] No dump file found for T=${{T}} K using pattern $pattern" | tee -a rdf_process.log
            continue
        fi

        out_dir="rdf_${{T}}K"
        mkdir -p "$out_dir"
        dump_abs="$(pwd)/$candidate"
        echo "[INFO] RDF at T=${{T}} K from $candidate -> $out_dir" | tee -a rdf_process.log

        (
            cd "$out_dir" || exit 1
            python "$SCRIPT_DIR/17_get_rdf_from_vmd.py" "$dump_abs" {rmax} {dr} 2>&1 | tee -a ../rdf_process.log

            {pair_expr}
            existing=()
            for f in "${{dat_files[@]}}"; do
                [[ -f "$f" ]] && existing+=("$f")
            done
            if [[ ${{#existing[@]}} -eq 0 ]]; then
                echo "[ERROR] No matching RDF .dat files found for T=${{T}} K" | tee -a ../rdf_process.log
                exit 0
            fi

            echo "[INFO] CN at T=${{T}} K" | tee -a ../rdf_process.log
            python "$SCRIPT_DIR/18_get_CN_from_rdf.py" "${{existing[@]}}" 2>&1 | tee -a ../rdf_process.log
        )
    done
    cd ..
done
"""
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)


def prepare_scripts(cfg):
    copy_scripts()
    patch_doping_script(cfg)
    patch_msd_script(cfg)
    patch_creator_script(cfg)
    patch_post_processor(cfg)
    patch_rdf_script(cfg)


def run_command(label, cmd):
    start = datetime.now()
    log(f"START {label}: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        cwd=RUN_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line)
    rc = proc.wait()
    elapsed = datetime.now() - start
    if rc != 0:
        log(f"FAIL {label}: rc={rc}, elapsed={elapsed}")
        raise subprocess.CalledProcessError(rc, cmd)
    log(f"PASS {label}: elapsed={elapsed}")


def run_pipeline(cfg):
    stages = cfg.get("stages", {}) or {}
    prepare_scripts(cfg)

    if stages.get("doping", True):
        run_command("doping", ["bash", str(SCRIPT_WORK_DIR / "creator_optimiser_docker.sh")])

    if stages.get("energy_comparison", True):
        run_command("energy_comparison", ["bash", str(SCRIPT_WORK_DIR / "csv_editor__energy_comparator.sh")])
        if cfg.get("run_trend_plots", True):
            run_command("trend_plots", ["bash", str(SCRIPT_WORK_DIR / "trend_plotter.sh")])

    if stages.get("md", True):
        cmd = ["bash", str(SCRIPT_WORK_DIR / "md_runner.sh")]
        run_command("md", cmd)

    if stages.get("post_processing", True):
        run_command("post_processing", ["bash", str(SCRIPT_WORK_DIR / "md_post_processor.sh")])

    if stages.get("rdf", True) and cfg.get("run_rdf", True):
        run_command("rdf", ["bash", str(SCRIPT_WORK_DIR / "get_rdf.sh")])

    if stages.get("summary", True):
        run_command("summary", [sys.executable, str(ROOT / "summary_writer.py"), "--root", str(RUN_ROOT)])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the LLZO workflow from input.yaml.")
    parser.add_argument("--input", default="input.yaml", help="Path to YAML input file")
    args = parser.parse_args(argv)

    input_path = resolve_path(args.input, ROOT)
    cfg = load_config(input_path)
    configure_runtime(cfg)
    LOG_FILE.write_text("", encoding="utf-8")
    validate_config(cfg)
    log("Pipeline input loaded")
    log(f"Code directory: {ROOT}")
    log(f"Run/output directory: {RUN_ROOT}")
    log("Effective input: " + json.dumps(cfg, sort_keys=True))
    run_pipeline(cfg)
    log("Pipeline complete")


if __name__ == "__main__":
    main()
