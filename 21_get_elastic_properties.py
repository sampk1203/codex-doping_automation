#!/usr/bin/env python
import glob
import os
import sys
import numpy as np
import pandas as pd
from ase.optimize import BFGS
from ase.io import read
from elastic import get_elementary_deformations, get_elastic_tensor
from orb_models.forcefield import pretrained
from orb_models.forcefield.calculator import ORBCalculator
import ase.units as units

# === STEP 0: Get folder paths ===
if len(sys.argv) < 2:
    print("Usage: python 21_get_elastic_properties.py <folder1> [<folder2> ...]")
    sys.exit(1)

folders = sys.argv[1:]
print("Folders to process:")
for f in folders:
    print(f"  - {f}")

# === STEP 1: Load ORB ML model ===
device = "cuda"  # or "cpu"
orbff = pretrained.orb_v3_conservative_inf_omat(device=device, precision="float32-high")
calc = ORBCalculator(orbff, device=device)

# === STEP 2: Loop over folders ===
for folder_path in folders:
    if not os.path.isdir(folder_path):
        print(f"\n❌ Skipping invalid directory: {folder_path}")
        continue

    print("\n" + "#"*120)
    print(f"### Processing folder: {folder_path}")
    print("#"*120)

    cif_files = sorted(glob.glob(os.path.join(folder_path, "*.cif")))
    if not cif_files:
        print(f"No .cif files found in {folder_path}. Skipping...")
        continue

    print(f"Found {len(cif_files)} CIF files:")
    for f in cif_files:
        print(f"  - {os.path.basename(f)}")

    # === STEP 3: Loop over CIF files in the folder ===
    for cif_file in cif_files:
        print("\n" + "="*100)
        print(f"Processing structure: {os.path.basename(cif_file)}")
        print("="*100)

        atoms = read(cif_file)
        atoms.calc = calc

        # --- Relax structure ---
        print("Initial Energy:", atoms.get_potential_energy())
        log_name = os.path.join(folder_path, f"{os.path.splitext(os.path.basename(cif_file))[0]}_relax.log")
        dyn = BFGS(atoms, logfile=log_name)
        dyn.run(fmax=0.02)
        print("Relaxed Energy:", atoms.get_potential_energy())

        # --- Elastic tensor parameters ---
        n_values = [3, 5, 7]
        d_values = [0.1, 0.2, 0.3]

        results = []
        all_C_matrices = []

        for n in n_values:
            for d in d_values:
                print(f"\n=== Elastic calculation: n={n}, d={d} ===")
                systems = get_elementary_deformations(atoms, n=n, d=d)
                for s in systems:
                    s.calc = calc
                    s.get_potential_energy()
                Cij, Bij = get_elastic_tensor(atoms, systems=systems)
                Cij_GPa = Cij / units.GPa
                all_C_matrices.append(Cij_GPa)

                # --- Print full 6×6 matrix ---
                print("\n--- Elastic Stiffness Matrix (GPa) ---")
                print(np.array_str(Cij_GPa, precision=2, suppress_small=True))

                # --- Extract key constants ---
                C11, C12, C44 = Cij_GPa[0], Cij_GPa[3], Cij_GPa[6]
                bulk = (C11 + 2 * C12) / 3
                shear = (C11 - C12 + 3 * C44) / 5
                youngs = 9 * bulk * shear / (3 * bulk + shear)
                poisson = (3 * bulk - 2 * shear) / (2 * (3 * bulk + shear))

                print(f"C11={C11:.2f} GPa, C12={C12:.2f} GPa, C44={C44:.2f} GPa")
                print(f"Bulk={bulk:.2f} GPa, Shear={shear:.2f} GPa, "
                      f"Young={youngs:.2f} GPa, Poisson={poisson:.4f}")

                results.append({
                    'n': n, 'd': d,
                    'C11': C11, 'C12': C12, 'C44': C44,
                    'bulk': bulk, 'shear': shear,
                    'youngs': youngs, 'poisson': poisson
                })

        # --- Average elastic constants ---
        C_array = np.array(all_C_matrices)
        C_avg = np.mean(C_array, axis=0)
        print("\n=== AVERAGED RESULTS ===")
        print(np.array_str(C_avg, precision=2, suppress_small=True))

        C11_avg, C12_avg, C44_avg = C_avg[0], C_avg[3], C_avg[6]
        bulk_avg = (C11_avg + 2 * C12_avg) / 3
        shear_avg = (C11_avg - C12_avg + 3 * C44_avg) / 5
        youngs_avg = 9 * bulk_avg * shear_avg / (3 * bulk_avg + shear_avg)
        poisson_avg = (3 * bulk_avg - 2 * shear_avg) / (2 * (3 * bulk_avg + shear_avg))

        print(f"\nC11={C11_avg:.2f} GPa, C12={C12_avg:.2f} GPa, C44={C44_avg:.2f} GPa")
        print(f"Bulk={bulk_avg:.2f} GPa, Shear={shear_avg:.2f} GPa, "
              f"Young={youngs_avg:.2f} GPa, Poisson={poisson_avg:.4f}")

        results.append({
            'n': 'avg', 'd': 'avg',
            'C11': C11_avg, 'C12': C12_avg, 'C44': C44_avg,
            'bulk': bulk_avg, 'shear': shear_avg,
            'youngs': youngs_avg, 'poisson': poisson_avg
        })

        # --- Save to CSV ---
        csv_name = os.path.join(folder_path,
                                f"{os.path.splitext(os.path.basename(cif_file))[0]}_elastic_scan_results.csv")
        df = pd.DataFrame(results)
        df.to_csv(csv_name, index=False)
        print(f"\n✅ Results saved to: {csv_name}")
