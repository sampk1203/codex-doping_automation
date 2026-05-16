# cif_to_lammps.py

import sys
from pymatgen.core import Structure
from pymatgen.io.lammps.data import LammpsData
from pymatgen.io.xyz import XYZ


# ---------------------------------------------
# CIF → LAMMPS (.data), XYZ, element_list
# ---------------------------------------------

def get_ordered_elements(lammps_data):
    """
    Return element symbols in the exact atom-type order pymatgen assigned
    them when building the LammpsData object.

    How pymatgen assigns types:
      LammpsData.from_structure() iterates the Structure sites in order and
      assigns a new integer type each time it encounters a species it hasn't
      seen before. The resulting type ordering is therefore identical to the
      order of first-appearance of each species in lammps_data.structure.

    The masses DataFrame index is just [1, 2, 3, ...] integers and the
    written Masses block contains no element comments, so both of those
    are useless for reverse-lookup. Reading the structure is the only
    reliable approach.
    """
    seen = []
    seen_set = set()
    for site in lammps_data.structure:
        sym = site.specie.symbol
        if sym not in seen_set:
            seen_set.add(sym)
            seen.append(sym)
    return seen


def convert_cif_to_outputs(cif_file):
    try:
        structure = Structure.from_file(cif_file)
        print(f"[INFO] Read structure with {len(structure)} atoms.")

        output_data = "lmp.data"

        # Build LammpsData object — keep a reference BEFORE writing so
        # we can read the type ordering from it directly.
        lammps_data = LammpsData.from_structure(structure, atom_style="charge")
        lammps_data.write_file(output_data)
        print(f"[SUCCESS] Wrote LAMMPS data file: {output_data}")

        # Write XYZ file
        xyz_output = "lmp.xyz"
        XYZ(structure).write_file(xyz_output)
        print(f"[SUCCESS] Wrote XYZ file: {xyz_output}")

        # Derive element list from first-appearance order in the structure,
        # which is exactly how pymatgen assigns LAMMPS atom types.
        elements = get_ordered_elements(lammps_data)

        # Cross-check: number of unique elements must equal number of mass rows.
        n_types = len(lammps_data.masses)
        if len(elements) != n_types:
            raise RuntimeError(
                f"Element count mismatch: got {len(elements)} species from structure "
                f"but {n_types} type rows in Masses block. "
                f"Check for partially-occupied or disordered sites in the CIF."
            )

        with open("element_list", "w") as f:
            f.write(" ".join(elements) + "\n")

        print(f"[SUCCESS] Wrote element_list: {' '.join(elements)}")

    except Exception as e:
        print(f"[ERROR] {e}")
        raise


def print_usage():
    print("Usage: python cif_to_lammps.py <input.cif>")
    print("Output files: lmp.data, lmp.xyz, element_list")
    print("!!! Only for ML potentials (e.g., ORB, DeepMD) !!!")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("[ERROR] Invalid number of arguments.")
        print_usage()
    elif not sys.argv[1].endswith(".cif"):
        print("[ERROR] Input file must be a .cif file.")
        print_usage()
    else:
        convert_cif_to_outputs(sys.argv[1])
