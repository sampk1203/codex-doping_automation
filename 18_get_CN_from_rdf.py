#!/usr/bin/env python
"""
coord_number_plot.py — compute and visualize coordination numbers from RDF + intRDF data

Usage:
    python coord_number_plot.py *.dat

Each .dat file must have columns: r, g(r), int(g(r))
"""

import sys
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.signal import savgol_filter
from scipy.interpolate import interp1d


# ==========================
# FONT SIZE SETTINGS (edit here)
# ==========================
TITLE_FONTSIZE   = 14
AXES_FONTSIZE    = 12
CAPTION_FONTSIZE = 10
LEGEND_FONTSIZE  = 10
# ==========================


def find_first_minimum(r, g):
    """Find the first minimum after the first peak in an RDF curve robustly."""
    r = np.array(r)
    g = np.array(g)

    valid = g > 1e-6
    if not np.any(valid):
        return None, None, None
    r, g = r[valid], g[valid]

    window = max(5, int(len(g) * 0.05) | 1)
    smooth_g = savgol_filter(g, window_length=window, polyorder=3)

    peak_idx = np.argmax(smooth_g[: len(g) // 2])
    dg = np.gradient(smooth_g, r)
    zero_crossings = np.where((dg[:-1] < 0) & (dg[1:] > 0))[0]
    zero_crossings = zero_crossings[zero_crossings > peak_idx]

    if len(zero_crossings) > 0:
        i0 = zero_crossings[0]
        search_end = min(i0 + 20, len(g))
        min_idx = np.argmin(g[i0:search_end]) + i0
    else:
        min_idx = np.argmin(g[peak_idx:]) + peak_idx

    return min_idx, r[min_idx], g[min_idx]


def get_cn_from_intrdf(r, gint, r_min):
    """Interpolate the integrated RDF at the detected r_min."""
    f = interp1d(r, gint, kind="linear", bounds_error=False, fill_value="extrapolate")
    return float(f(r_min))


def process_file(filename):
    """Process a single RDF file and compute CN."""
    try:
        data = np.loadtxt(filename, comments=("#", "@"))
    except Exception as e:
        print(f"❌ Error reading {filename}: {e}")
        return None

    if data.shape[1] < 3:
        print(f"⚠️ File {filename} has less than 3 columns.")
        return None

    r, g, gint = data[:, 0], data[:, 1], data[:, 2]
    i_min, r_min, g_min = find_first_minimum(r, g)
    if i_min is None:
        print(f"⚠️ Could not find minimum in {filename}.")
        return None

    cn = get_cn_from_intrdf(r, gint, r_min)
    return (filename, r, g, gint, r_min, g_min, cn)


def main():
    if len(sys.argv) < 2:
        print("Usage: python coord_number_plot.py file1.dat [file2.dat ...]")
        sys.exit(1)

    files = sorted(sys.argv[1:], key=lambda f: Path(f).name)
    results = []

    for f in files:
        res = process_file(f)
        if res:
            results.append(res)

    if not results:
        print("⚠️ No valid RDF files processed.")
        sys.exit(0)

    print("\n=== Coordination Number Summary ===\n")
    for fname, r, g, gint, r_min, g_min, cn in results:
        print(f"{Path(fname).name:20s}  CN = {cn:.4f}  (r_min = {r_min:.4f} Å)")

        # --- Plot RDF and intRDF ---
        fig, ax1 = plt.subplots(figsize=(7, 4))
        ax2 = ax1.twinx()

        # RDF
        l1, = ax1.plot(r, g, color='tab:blue', lw=1.5, label='g(r)')
        ax1.set_xlabel("r (Å)", fontsize=AXES_FONTSIZE)
        ax1.set_ylabel("g(r) ", color='tab:blue', fontsize=AXES_FONTSIZE)
        ax1.tick_params(axis='y', labelcolor='tab:blue')

        # intRDF
        l2, = ax2.plot(r, gint, color='tab:orange', alpha=0.5, lw=1.5, label='∫g(r)')
        ax2.set_ylabel("∫g(r)", color='tab:orange', fontsize=AXES_FONTSIZE)
        ax2.tick_params(axis='y', labelcolor='tab:orange')

        # mark r_min and CN
        ax1.axvline(r_min, color='gray', ls='--', lw=1)
        ax1.text(
            r_min, g_min,
            f"rₘᵢₙ={r_min:.2f} Å\nCN={cn:.2f}",
            color='black', fontsize=CAPTION_FONTSIZE, ha='left', va='bottom',
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.7)
        )

        # No title (explicitly removed)

        # Save figure in same folder as input file
        out_path = Path(fname).parent / "rdf.png"
        fig.tight_layout()
        fig.savefig(out_path, dpi=300)
        plt.close(fig)



if __name__ == "__main__":
    main()
