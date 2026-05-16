import os
import glob
import re
from ase.io import read, write
from ase.optimize import BFGS
from ase.constraints import UnitCellFilter
from orb_models.forcefield import pretrained
from orb_models.forcefield.calculator import ORBCalculator


def natural_sort_key(s):
    """Sort strings with numbers in human order, e.g., 2 < 10"""
    return [
        int(text) if text.isdigit() else text.lower()
        for text in re.split(r"(\d+)", s)
    ]


# ---- Model registry ----
MODEL_REGISTRY = {
    1: {
        "name": "orb_v3_conservative_inf_omat",
        "loader": lambda: pretrained.orb_v3_conservative_inf_omat(
            device="cuda", precision="float32-high"
        ),
    },
    2: {
        "name": "orb_v3_direct_inf_omat",
        "loader": lambda: pretrained.orb_v3_direct_inf_omat(
            device="cuda", precision="float32-high"
        ),
    },
    3: {
        "name": "orb_v3_conservative_20_omat",
        "loader": lambda: pretrained.orb_v3_conservative_20_omat(
            device="cuda", precision="float32-high"
        ),
    },
    4: {
        "name": "orb_v3_direct_20_omat",
        "loader": lambda: pretrained.orb_v3_direct_20_omat(
            device="cuda", precision="float32-high"
        ),
    },
    5: {
        "name": "orb_v3_conservative_inf_mpa",
        "loader": lambda: pretrained.orb_v3_conservative_inf_mpa(
            device="cuda", precision="float32-high"
        ),
    },
    6: {
        "name": "orb_v3_direct_inf_mpa",
        "loader": lambda: pretrained.orb_v3_direct_inf_mpa(
            device="cuda", precision="float32-high"
        ),
    },
    7: {
        "name": "orb_v3_conservative_20_mpa",
        "loader": lambda: pretrained.orb_v3_conservative_20_mpa(
            device="cuda", precision="float32-high"
        ),
    },
    8: {
        "name": "orb_v3_direct_20_mpa",
        "loader": lambda: pretrained.orb_v3_direct_20_mpa(
            device="cuda", precision="float32-high"
        ),
    },
}


def relax_cifs(folder, model_id):
    print(f"--- Processing folder: {folder} ---")

    # Get CIF files sorted naturally
    cif_files = sorted(glob.glob(os.path.join(folder, "*.cif")), key=natural_sort_key)
    if not cif_files:
        print(f"No CIF files found in {folder}")
        return

    # Load selected ORB model + calculator (only once per folder)
    model_entry = MODEL_REGISTRY[model_id]
    print(f"Using model [{model_id}]: {model_entry['name']}")

    orbff = model_entry["loader"]()
    calc = ORBCalculator(orbff, device="cuda")

    results = []

    for cif_file in cif_files:
        # Skip files that are already relaxed
        if cif_file.endswith("_relaxed.cif"):
            continue

        # Skip if a relaxed version already exists
        relaxed_file = cif_file.replace(".cif", "_relaxed.cif")
        if os.path.exists(relaxed_file):
            print(f"Skipping {cif_file}, relaxed version already exists.")
            continue

        atoms = read(cif_file)
        atoms.calc = calc

        ucf = UnitCellFilter(atoms)
        dyn = BFGS(ucf, logfile='-')
        dyn.run(fmax=0.05)

        energy = atoms.get_potential_energy()
        results.append((os.path.basename(cif_file), energy))

        write(relaxed_file, atoms)
        print(f"Relaxed: {relaxed_file} | Energy: {energy:.6f} eV")

    # Sort naturally
    results.sort(key=lambda x: natural_sort_key(x[0]))

    # Write energies
    energies_file = os.path.join(folder, "energies.txt")

    file_exists = os.path.exists(energies_file)
    mode = "a" if file_exists else "w"

    with open(energies_file, mode) as f:
        for fname, e in results:
            f.write(f"{fname}\t{e:.6f}\n")

    print(f"All energies written to {energies_file}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Relax CIF files in one or more folders using ORBModels."
    )
    parser.add_argument(
        "folders",
        nargs="+",
        help="One or more folders containing CIF files"
    )
    parser.add_argument(
        "--model",
        type=int,
        default=1,
        choices=MODEL_REGISTRY.keys(),
        help=(
            "Model selection:\n"
            "1 = orb_v3_conservative_inf_omat (default)\n"
            "2 = orb_v3_direct_inf_omat\n"
            "3 = orb_v3_conservative_20_omat\n"
            "4 = orb_v3_direct_20_omat\n"
            "5 = orb_v3_conservative_inf_mpa\n"
            "6 = orb_v3_direct_inf_mpa"
            "7 = orb_v3_conservative_20_mpa"
            "8 = orb_v3_direct_20_mpa"
        ),
    )

    args = parser.parse_args()

    for folder in args.folders:
        relax_cifs(folder, args.model)
