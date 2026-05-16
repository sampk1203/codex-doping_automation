import os
import sys
import csv
from itertools import combinations, product
from pymatgen.core import Structure, Element
from pymatgen.io.cif import CifWriter
import warnings
warnings.filterwarnings(
    "ignore",
    message="Site labels are not unique"
)


# ===================== USER INPUT =====================
INPUT_CIF = "cubic-LLZO.cif"
SUPERCELL = (1, 1, 2)  # (x, y, z)
OUTPUT_DIR = "./run_1"

MAX_FILES_PER_FOLDER = 1000

# Distance limits (set to None to disable)
DOP_DOP_MIN = None
DOP_DOP_MAX = None
DOP_ION_MIN = None
DOP_ION_MAX = 15
ION_ION_MIN = None
ION_ION_MAX = None

DOPANTS = [
    {
        "dopant": "Nb",
        "dopant_valency": 5,
        "host": "Zr",
        "host_valency": 4,
        "count": 1,
        "carrier": "Li",
        "carrier_valency": 1,
    },
    {
        "dopant": "Y",
        "dopant_valency": 3,
        "host": "La",
        "host_valency": 3,
        "count": 1,
        "carrier": "Li",
        "carrier_valency": 1,
    }
]
# =====================================================


def info(msg):
    print(f"[INFO] {msg}")


def error(msg):
    print(f"[ERROR] {msg}")
    sys.exit(1)


def within_limits(vals, dmin, dmax):
    if not vals:
        return True
    if dmin is not None and min(vals) < dmin:
        return False
    if dmax is not None and max(vals) > dmax:
        return False
    return True


# -------------------- load structure --------------------
if not os.path.exists(INPUT_CIF):
    error(f"CIF not found: {INPUT_CIF}")

os.makedirs(OUTPUT_DIR, exist_ok=True)
struct = Structure.from_file(INPUT_CIF)

# -------------------- build supercell --------------------
try:
    sx, sy, sz = SUPERCELL
except Exception:
    error("SUPERCELL must be (x,y,z)")

if not all(isinstance(v, int) and v > 0 for v in (sx, sy, sz)):
    error("SUPERCELL values must be positive integers")

if (sx, sy, sz) != (1, 1, 1):
    info(f"Building supercell {sx}x{sy}x{sz}")
    struct.make_supercell([sx, sy, sz])

# -------------------- atom statistics --------------------
atom_indices = {}
for i, s in enumerate(struct):
    atom_indices.setdefault(s.specie.symbol, []).append(i)

info("Atom counts after supercell:")
for el, idxs in atom_indices.items():
    info(f"  {el}: {len(idxs)}")
info(f"Total atoms: {len(struct)}")

# -------------------- validate dopants --------------------
carrier = DOPANTS[0]["carrier"]
carrier_valency = DOPANTS[0]["carrier_valency"]

# All dopant entries must share the same carrier — mixed carriers
# (e.g. one entry Li, another Na) are not supported.
carriers_defined = set(d["carrier"] for d in DOPANTS)
if len(carriers_defined) > 1:
    error(f"Multiple carrier types defined across DOPANTS: {carriers_defined}. Only one carrier allowed.")

if carrier not in atom_indices:
    error(f"Carrier {carrier} not present")

for d in DOPANTS:
    if d["dopant"] == d["host"]:
        error(f"Dopant and host are the same element ({d['dopant']}) — no substitution would occur.")
    if d["host"] not in atom_indices:
        error(f"Host {d['host']} not present")
    if d["count"] > len(atom_indices[d["host"]]):
        error(f"Not enough {d['host']} sites")

# -------------------- build dopant substitution pools --------------------
# If the dopant species already exists in the structure (e.g. a second
# doping pass, or a CIF that already contains some Nb), exclude those
# pre-existing sites from the host pool so they are never double-counted.
dopant_pools = []
for d in DOPANTS:
    pre_existing = set(atom_indices.get(d["dopant"], []))
    available_host_sites = [
        idx for idx in atom_indices[d["host"]]
        if idx not in pre_existing
    ]
    if d["count"] > len(available_host_sites):
        error(
            f"Not enough available {d['host']} sites for {d['dopant']} after "
            f"excluding {len(pre_existing)} pre-existing {d['dopant']} sites."
        )
    if pre_existing:
        info(
            f"[NOTE] {len(pre_existing)} pre-existing {d['dopant']} site(s) found "
            f"and excluded from substitution pool."
        )
    dopant_pools.append(list(combinations(available_host_sites, d["count"])))

# -------------------- charge balance --------------------
delta_charge = sum(
    d["count"] * (d["dopant_valency"] - d["host_valency"])
    for d in DOPANTS
)

if delta_charge < 0:
    error("Carrier insertion not supported")

if delta_charge % carrier_valency != 0:
    error("Charge imbalance not divisible by carrier valency")

n_remove = delta_charge // carrier_valency
info(f"Charge balance: remove {n_remove} {carrier}")

# -------------------- config files --------------------
avail_path = os.path.join(OUTPUT_DIR, "available_configs.txt")
sel_path = os.path.join(OUTPUT_DIR, "selected_configs.txt")

generate_available = not os.path.exists(avail_path)


def build_all_configs():
    """Enumerate all valid (non-overlapping) dopant site combinations."""
    configs = []
    for cfg in product(*dopant_pools):
        flat = [i for g in cfg for i in g]
        if len(flat) == len(set(flat)):
            configs.append(cfg)
    return configs


# -------------------- enumerate dopant configs --------------------
if generate_available:
    info("Generating available dopant configurations")
    all_configs = build_all_configs()

    with open(avail_path, "w") as f:
        f.write("Available dopant configurations\n\n")
        for idx, cfg in enumerate(all_configs, start=1):
            labels = []
            flat_sites = []
            for d, grp in zip(DOPANTS, cfg):
                for s in grp:
                    labels.append((d["dopant"], s + 1))
                    flat_sites.append(s)

            pairs = []
            for i in range(len(flat_sites)):
                for j in range(i + 1, len(flat_sites)):
                    dist = struct.get_distance(flat_sites[i], flat_sites[j])
                    pairs.append(
                        f"{labels[i][0]}{labels[i][1]}-"
                        f"{labels[j][0]}{labels[j][1]}:{dist:.4f}Å"
                    )

            f.write(f"{idx:4d}. sites={labels} distances: {', '.join(pairs)}\n")

    info(f"Written {avail_path}")
    info("Create selected_configs.txt and rerun")
    sys.exit(0)

# -------------------- load selections --------------------
with open(sel_path) as f:
    selected = [int(x) for x in f.read().split(",") if x.strip()]

info(f"Selected configs: {selected}")

# Rebuild all_configs fresh — same function as first pass, guaranteed identical ordering.
all_configs = build_all_configs()

# -------------------- generate selected configurations --------------------
for sel in selected:
    cfg = all_configs[sel - 1]

    flat_sites = []
    flat_species = []
    for d, grp in zip(DOPANTS, cfg):
        for s in grp:
            flat_sites.append(s)
            flat_species.append(d["dopant"])

    # ---- CORRECT carrier removal logic ----
    dopant_sites = set(flat_sites)
    carrier_removal_sites = sorted(
        set(atom_indices[carrier]) - dopant_sites
    )

    if n_remove > len(carrier_removal_sites):
        info(f"[SKIP] Config {sel}: insufficient removable carriers")
        continue

    carrier_removal_combos = (
        list(combinations(carrier_removal_sites, n_remove))
        if n_remove > 0 else [()]
    )

    folder = "_".join(f"{sp}{i+1}" for sp, i in zip(flat_species, flat_sites))
    folder = os.path.join(OUTPUT_DIR, folder)
    os.makedirs(folder, exist_ok=True)

    csv_path = os.path.join(folder, "pair_distances.csv")
    written = 0

    # Pre-compute CSV header labels from flat_sites/flat_species alone —
    # they are the same for every rm combo, so we can write the header
    # once up front regardless of whether any combo passes distance filters.
    header_labels = []
    for i in range(len(flat_sites)):
        for j in range(i + 1, len(flat_sites)):
            header_labels.append(
                f"{flat_species[i]}{flat_sites[i]+1}-"
                f"{flat_species[j]}{flat_sites[j]+1}"
            )
    # dop_ion and ion_ion labels depend on which rm combo is used, so we
    # use the first combo just to build column names (coords don't change).
    first_rm = carrier_removal_combos[0] if carrier_removal_combos else ()
    for i, ds in enumerate(flat_sites):
        for li in first_rm:
            header_labels.append(f"{flat_species[i]}{ds+1}-{carrier}{li+1}")
    for i in range(len(first_rm)):
        for j in range(i + 1, len(first_rm)):
            header_labels.append(f"{carrier}{first_rm[i]+1}-{carrier}{first_rm[j]+1}")

    with open(csv_path, "w", newline="") as csvf:
        writer = csv.writer(csvf)
        writer.writerow(["Dopant_Sites", "Carrier_Removed"] + header_labels)

        for rm in carrier_removal_combos:
            if written >= MAX_FILES_PER_FOLDER:
                info(f"[WARNING] Config {sel}: reached MAX_FILES_PER_FOLDER ({MAX_FILES_PER_FOLDER}), remaining combos skipped.")
                break

            temp = struct.copy()

            for i, el in zip(flat_sites, flat_species):
                temp[i] = Element(el)

            dop_dop, dop_ion, ion_ion = [], [], []
            labels = []

            for i in range(len(flat_sites)):
                for j in range(i + 1, len(flat_sites)):
                    dop_dop.append(temp.get_distance(flat_sites[i], flat_sites[j]))
                    labels.append(
                        f"{flat_species[i]}{flat_sites[i]+1}-"
                        f"{flat_species[j]}{flat_sites[j]+1}"
                    )

            for i, ds in enumerate(flat_sites):
                for li in rm:
                    dop_ion.append(temp.get_distance(ds, li))
                    labels.append(
                        f"{flat_species[i]}{ds+1}-{carrier}{li+1}"
                    )

            for i in range(len(rm)):
                for j in range(i + 1, len(rm)):
                    ion_ion.append(temp.get_distance(rm[i], rm[j]))
                    labels.append(
                        f"{carrier}{rm[i]+1}-{carrier}{rm[j]+1}"
                    )

            if not (
                within_limits(dop_dop, DOP_DOP_MIN, DOP_DOP_MAX)
                and within_limits(dop_ion, DOP_ION_MIN, DOP_ION_MAX)
                and within_limits(ion_ion, ION_ION_MIN, ION_ION_MAX)
            ):
                continue

            writer.writerow(
                [
                    ";".join(f"{s}{i+1}" for s, i in zip(flat_species, flat_sites)),
                    ";".join(str(i+1) for i in rm) if rm else "None",
                ]
                + [f"{v:.4f}" for v in (dop_dop + dop_ion + ion_ion)]
            )

            for i in sorted(rm, reverse=True):
                temp.remove_sites([i])

            name = (
                f"{carrier}Removed-" + "_".join(str(i+1) for i in rm) + ".cif"
                if rm else "NoIonChange.cif"
            )

            CifWriter(temp).write_file(os.path.join(folder, name))
            written += 1

    info(f"[DONE] {folder}")

info("All selected configurations processed successfully.")
