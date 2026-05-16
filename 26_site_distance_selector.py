"""
pick_unique_distance_sets.py (group/thin version)

Writes BOTH:
  - selected_configs.txt              (comma-separated indices)
  - selected_configs_detailed.txt     (full representative lines)

New behavior:
After canonical duplicate filtering, structures are grouped by their FIRST
distance (exact float match). Inside each group, structures are sorted by
SECOND distance and alternate entries are selected (0,2,4,...). If structures
only have ONE distance, this thinning step is skipped.
"""

import re
import sys
import argparse
import os
from typing import List, Tuple, Dict

# --- Regex helpers ---
IDX_RE = re.compile(r'^\s*(\d+)\.\s*')
DISTANCES_LABEL_RE = re.compile(r'distances\s*:\s*(.*)$', re.IGNORECASE)
FLOAT_RE = re.compile(r'[-+]?\d*\.\d+')

def parse_distances_from_line(line: str) -> List[float]:
    m = DISTANCES_LABEL_RE.search(line)
    if not m:
        return []
    floats = FLOAT_RE.findall(m.group(1))
    return [float(x) for x in floats]

def canonical_key(distances: List[float], tol: float) -> Tuple[int, Tuple[int, ...]]:
    sorted_d = sorted(distances)
    quantized = tuple(int(round(d / tol)) for d in sorted_d)
    return (len(sorted_d), quantized)

def pick_unique(lines: List[str], tol: float=1e-3) -> List[Tuple[int, str, List[float]]]:
    """Return list of (index, line, distances) after canonical uniqueness."""
    seen = {}
    order = []
    results = []

    for line in lines:
        m = IDX_RE.match(line)
        if not m:
            continue

        idx = int(m.group(1))
        dist = parse_distances_from_line(line)
        key = canonical_key(dist, tol) if dist else ("no_distances", idx)

        if key not in seen:
            seen[key] = True
            order.append((idx, line, dist))

    # Sort by index
    order.sort(key=lambda x: x[0])
    return order

def group_and_thin(reps: List[Tuple[int, str, List[float]]]) -> List[Tuple[int, str]]:
    """Apply the new grouping + balanced 5-point selection rule."""
    if not reps:
        return []

    # Determine number of distances
    num_dists = len(reps[0][2])
    if num_dists <= 1:
        # Only one distance → no thinning needed
        return [(idx, line) for idx, line, _ in reps]

    # --- Group by exact first distance ---
    groups: Dict[float, List[Tuple[int, str, List[float]]]] = {}
    for entry in reps:
        idx, line, dist = entry
        first = dist[0]
        groups.setdefault(first, []).append(entry)

    selected: List[Tuple[int, str]] = []

    for first_dist, group in groups.items():
        # Sort group by second distance
        group_sorted = sorted(group, key=lambda x: x[2][1])

        n = len(group_sorted)

        if n <= 2:
            # Keep all
            for idx, line, _ in group_sorted:
                selected.append((idx, line))
            continue

        if n <= 4:
            # Pick min, avg, max
            min_idx = 0
            max_idx = n - 1
            avg_idx = n // 2  # upper middle for even
            pick_indices = sorted({min_idx, avg_idx, max_idx})
        else:
            # General case: pick 5 points
            min_idx = 0
            max_idx = n - 1
            avg_idx = n // 2  # upper average ALWAYS

            mid_left = (min_idx + avg_idx) // 2
            mid_right = (avg_idx + max_idx) // 2

            # up to 5 unique picks
            pick_indices = sorted({min_idx, mid_left, avg_idx, mid_right, max_idx})

        # Append selected from this group
        for pi in pick_indices:
            idx, line, _ = group_sorted[pi]
            selected.append((idx, line))

    # Sort final selection by structure index
    selected.sort(key=lambda x: x[0])
    return selected


def main(argv):
    parser = argparse.ArgumentParser(description="Select unique representatives by distance sets.")
    parser.add_argument("infile", help="Input file (e.g., available_configs.txt)")
    parser.add_argument("--tol", type=float, default=1e-3, help="Tolerance for distance quantization")
    parser.add_argument("--out", required=True, help="Output file or folder")
    args = parser.parse_args(argv)

    # --- Determine output directory ---
    out_path = args.out

    if out_path.endswith("/"):
        out_dir = out_path
        index_file = os.path.join(out_dir, "selected_configs.txt")
    else:
        out_dir = os.path.dirname(out_path) or "."
        index_file = out_path

    detailed_file = os.path.join(out_dir, "selected_configs_detailed.txt")
    os.makedirs(out_dir, exist_ok=True)

    # --- Load input ---
    with open(args.infile, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Step 1: canonical uniqueness
    reps_unique = pick_unique(lines, tol=args.tol)

    # Step 2: new grouping + thinning rule
    final_reps = group_and_thin(reps_unique)

    # --- Write detailed file ---
    with open(detailed_file, "w", encoding="utf-8") as fdet:
        for idx, line in final_reps:
            fdet.write(line.rstrip() + "\n")

    # --- Write index file ---
    indices = [str(idx) for idx, _ in final_reps]
    with open(index_file, "w", encoding="utf-8") as fout:
        fout.write(",".join(indices) + "\n")

    print(f"[INFO] Wrote detailed file: {detailed_file}")
    print(f"[INFO] Wrote index file: {index_file}")
    print(f"[INFO] Total selected: {len(indices)}")

if __name__ == "__main__":
    main(sys.argv[1:])
