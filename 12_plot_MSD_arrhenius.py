#!/usr/bin/env python
import sys
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import linregress
import os
import re
from ase.io import read

# Disable interactive plotting
plt.ioff()

# ==============================
# User-defined parameters
# ==============================

# Plot modes: 1 - Linear, 2 - Log-Log, 3 - Semi-Log (Y)
PLOT_MODES = [1, 2, 3]

# Fitting range in ps (adjust to the diffusive regime of your MSD)
X_START = 100
X_END = 200

# Reference temperature for conductivity (K)
T_REF = 300

# Carrier species to count and track (Li for LLZO, Na for NASICON etc.)
# Set to None to auto-detect as the lightest mobile ion found in the CIF.
CARRIER_SPECIES = None   # e.g. "Li" or "Na" — None = auto-detect

# ==============================
# Helper Functions
# ==============================

# Ordered list of typical mobile-ion candidates (lightest first)
_MOBILE_ION_CANDIDATES = ["Li", "Na", "K", "Ag", "Cu"]


def detect_carrier(atoms):
    """Return the first mobile-ion species found in the structure."""
    symbols = set(atoms.get_chemical_symbols())
    for candidate in _MOBILE_ION_CANDIDATES:
        if candidate in symbols:
            return candidate
    raise ValueError(
        f"Could not auto-detect carrier species. "
        f"Set CARRIER_SPECIES manually. Found species: {symbols}"
    )


def get_cif_volume_m3(cif_path):
    """Read unit-cell volume from CIF in m^3 (ASE gives Angstrom^3)."""
    atoms = read(cif_path)
    vol_angstrom3 = atoms.get_volume()     # Angstrom^3
    vol_m3 = vol_angstrom3 * 1e-30        # 1 Angstrom^3 = 1e-30 m^3
    return vol_m3


def count_carrier_in_cif(cif_path, carrier):
    atoms = read(cif_path)
    symbols = atoms.get_chemical_symbols()
    return symbols.count(carrier)


def find_cif_in_folder(folder):
    files = [f for f in os.listdir(folder) if f.lower().endswith(".cif")]
    if len(files) == 0:
        raise FileNotFoundError(f"No CIF file found in folder: {folder}")
    if len(files) > 1:
        raise RuntimeError(f"More than one CIF found in: {folder}")
    return os.path.join(folder, files[0])


def read_file(filename):
    try:
        data = np.loadtxt(filename, delimiter=",", skiprows=1)
    except ValueError:
        data = np.loadtxt(filename, skiprows=1)
    return data[:, 1], data[:, 2]


def extract_temperature_from_filename(filename):
    numbers = re.findall(r'\d+', os.path.basename(filename))
    if not numbers:
        raise ValueError(f"No temperature found in filename: {filename}")
    return float(numbers[-1])


def linear_fit(x, y, x_start, x_end):
    mask = (x >= x_start) & (x <= x_end)
    x_fit = x[mask]
    y_fit = y[mask]
    slope, intercept, *_ = linregress(x_fit, y_fit)
    return slope, intercept, x_fit, slope * x_fit + intercept


def plot_all_final(all_data, fit_curves, plot_modes, outfolder):
    n = len(plot_modes)
    plt.figure(figsize=(6 * n, 5))
    colors = plt.cm.tab10.colors

    for i, mode in enumerate(plot_modes, start=1):
        plt.subplot(1, n, i)

        for idx, (filename, (x, y)) in enumerate(all_data.items()):
            c = colors[idx % len(colors)]
            if mode == 1:
                plt.plot(x, y, color=c)
            elif mode == 2:
                plt.loglog(x, y, color=c)
            elif mode == 3:
                plt.semilogy(x, y, color=c)

        for idx, (filename, (xf, yf)) in enumerate(fit_curves.items()):
            c = colors[idx % len(colors)]
            plt.plot(xf, yf, "--", color=c, alpha=0.5)

        plt.xlabel("Time (ps)")
        plt.ylabel("MSD (Å$^2$)")
        plt.grid(True)

    plt.tight_layout()
    outfile = os.path.join(outfolder, "MSD_all_plots.png")
    plt.savefig(outfile, dpi=600, bbox_inches="tight")
    plt.close()


def arrhenius_fit(temps, diffusivities, outfolder):
    temps = np.array(temps)
    diffusivities = np.array(diffusivities)
    x_arr = 1000.0 / temps
    y_arr = np.log(diffusivities)

    slope, intercept, *_ = linregress(x_arr, y_arr)
    y_fit = slope * x_arr + intercept

    plt.figure(figsize=(6, 4))
    plt.scatter(x_arr, y_arr)
    plt.plot(x_arr, y_fit, "r--")
    plt.xlabel("1000 / T (1/K)")
    plt.ylabel("ln(D)")
    plt.grid(True)

    outfile = os.path.join(outfolder, "Arrhenius_plot.png")
    plt.savefig(outfile, dpi=600, bbox_inches="tight")
    plt.close()

    D0 = np.exp(intercept)
    Ea = -slope * 8.615e-2  # eV
    return slope, intercept, D0, Ea

# ==============================
# Main
# ==============================

def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py MD_run_folder/")
        sys.exit(1)

    folder = sys.argv[1]

    # Locate the CIF — it is the relaxed/doped structure used for this MD run,
    # so its cell volume and atom count are exactly what the simulation saw.
    cif_path = find_cif_in_folder(folder)

    # Auto-detect carrier or use override
    atoms_cif = read(cif_path)
    carrier = CARRIER_SPECIES if CARRIER_SPECIES else detect_carrier(atoms_cif)
    carrier_count = atoms_cif.get_chemical_symbols().count(carrier)

    # Volume comes directly from the CIF cell — no hardcoded magic number.
    # The CIF stored in MD_run_* is already the exact supercell used in LAMMPS,
    # so volume_m3 is the total simulation volume, not a unit-cell times N.
    volume_m3 = get_cif_volume_m3(cif_path)

    print(f"[INFO] CIF: {cif_path}")
    print(f"[INFO] Carrier species: {carrier}")
    print(f"[INFO] Carrier count in CIF: {carrier_count}")
    print(f"[INFO] Cell volume: {volume_m3:.4e} m^3")

    # Collect MSD files
    filenames = sorted(
        [os.path.join(folder, f) for f in os.listdir(folder)
         if "msd" in f.lower() and f.endswith(".txt")]
    )

    if not filenames:
        print(f"[ERROR] No MSD .txt files found in {folder}")
        sys.exit(1)

    # Read, fit, compute diffusivity per temperature
    temps = []
    diffusivities = []
    all_data = {}
    fit_curves = {}

    for filename in filenames:
        x, y = read_file(filename)
        temp = extract_temperature_from_filename(filename)
        slope, intercept, xfit, yfit = linear_fit(x, y, X_START, X_END)

        # MSD slope is in Å²/ps; factor of 6 for 3D, ×1e-20/1e-12 → cm²/s
        # slope [Å²/ps] / 6 × (1e-16 cm²/Å²) / (1e-12 s/ps) = slope/6 × 1e-4 cm²/s
        # Simplified: D [cm²/s] = slope / 60000
        Diff = slope / 60000.0
        print(f"  {os.path.basename(filename)}: T={temp:.0f} K, D={Diff:.3e} cm²/s")

        temps.append(temp)
        diffusivities.append(Diff)
        all_data[filename] = (x, y)
        fit_curves[filename] = (xfit, yfit)

    # MSD plot
    plot_all_final(all_data, fit_curves, PLOT_MODES, folder)

    # Arrhenius fit
    slope_arr, intercept_arr, D0, Ea = arrhenius_fit(temps, diffusivities, folder)
    print(f"\n[Arrhenius] D0 = {D0:.3e} cm²/s,  Ea = {Ea:.4f} eV")

    # ===========================
    # Ionic conductivity
    # ===========================
    # n_density: number of carriers per m³
    # volume_m3 is already the full simulation cell volume read from the CIF
    n_density = carrier_count / volume_m3

    kB = 8.617333262145e-5  # eV/K
    D_Tref = D0 * np.exp(-Ea / (kB * T_REF))  # cm²/s at T_REF

    # Nernst-Einstein: σ = n q² D / (kB T)
    # with q = e (elementary charge), D in m²/s, n in m⁻³
    # σ [S/m] = n [m⁻³] × (1.602e-19)² [C²] × D [m²/s]
    #           / (kB_SI [J/K] × T [K])
    # Precomputed constant for D in cm²/s → m²/s (*1e-4):
    #   (1.602e-19)² / 1.381e-23 = 1.859e-15  →  ×1e-4 = 1.859e-19
    # σ [S/m] = n × 1.859e-19 × D_cm2s / T_REF
    sigma = n_density * 1.859e-19 * D_Tref / T_REF

    print(f"\n=== Conductivity at T={T_REF} K ===")
    print(f"  Carrier:          {carrier}  (count = {carrier_count})")
    print(f"  Volume:           {volume_m3:.4e} m^3")
    print(f"  Number density:   {n_density:.4e} m^-3")
    print(f"  D({T_REF} K):      {D_Tref:.3e} cm^2/s")
    print(f"  σ:                {sigma:.3e} S/m")


if __name__ == "__main__":
    main()
