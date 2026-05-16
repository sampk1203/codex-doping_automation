#!/usr/bin/env python3
import csv
import re
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "summary.txt"


PATTERNS = {
    "carrier": re.compile(r"Carrier(?: species)?:\s+([A-Za-z]+)"),
    "count": re.compile(r"Carrier count in CIF:\s+(\d+)"),
    "volume": re.compile(r"Cell volume:\s+([0-9.eE+-]+)"),
    "d0_ea": re.compile(r"D0\s*=\s*([0-9.eE+-]+).*Ea\s*=\s*([0-9.eE+-]+)"),
    "sigma": re.compile(r"\bsigma\b|σ", re.IGNORECASE),
    "sigma_value": re.compile(r"(?:σ|sigma)\s*:\s*([0-9.eE+-]+)", re.IGNORECASE),
    "elastic": re.compile(
        r"Bulk=([0-9.eE+-]+).*Shear=([0-9.eE+-]+).*Young=([0-9.eE+-]+).*Poisson=([0-9.eE+-]+)"
    ),
    "cn": re.compile(r"(\S+\.dat)\s+CN\s*=\s*([0-9.eE+-]+)\s+\(r_min\s*=\s*([0-9.eE+-]+)"),
}


def parse_analysis_log(path):
    data = {
        "carrier": "",
        "count": "",
        "volume": "",
        "ea": "",
        "d0": "",
        "sigma": "",
        "bulk": "",
        "shear": "",
        "young": "",
        "poisson": "",
    }
    if not path.exists():
        return data

    for line in path.read_text(errors="replace").splitlines():
        if not data["carrier"]:
            m = PATTERNS["carrier"].search(line)
            if m:
                data["carrier"] = m.group(1)
        if not data["count"]:
            m = PATTERNS["count"].search(line)
            if m:
                data["count"] = m.group(1)
        if not data["volume"]:
            m = PATTERNS["volume"].search(line)
            if m:
                data["volume"] = m.group(1)
        m = PATTERNS["d0_ea"].search(line)
        if m:
            data["d0"] = m.group(1)
            data["ea"] = m.group(2)
        m = PATTERNS["sigma_value"].search(line)
        if m:
            data["sigma"] = m.group(1)
        m = PATTERNS["elastic"].search(line)
        if m:
            data["bulk"], data["shear"], data["young"], data["poisson"] = m.groups()
    return data


def parse_rdf_log(path):
    rows = []
    temp = ""
    if not path.exists():
        return rows
    for line in path.read_text(errors="replace").splitlines():
        mt = re.search(r"T=(\d+(?:\.\d+)?)\s*K", line)
        if mt:
            temp = mt.group(1)
        m = PATTERNS["cn"].search(line)
        if m:
            rows.append((temp, m.group(1), m.group(2), m.group(3)))
    return rows


def write_summary(root):
    root = Path(root).resolve()
    out = root / "summary.txt"
    md_dirs = sorted(root.glob("MD_run_*"), key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", p.name)])
    with out.open("w", encoding="utf-8", newline="") as fh:
        fh.write("LLZO Pipeline Summary\n")
        fh.write("=====================\n\n")

        writer = csv.writer(fh, delimiter="\t")
        writer.writerow([
            "Run",
            "Carrier",
            "Count",
            "Volume(m^3)",
            "Ea(eV)",
            "D0(cm^2/s)",
            "sigma@Tref(S/m)",
            "Bulk(GPa)",
            "Shear(GPa)",
            "Young(GPa)",
            "Poisson",
        ])
        for md in md_dirs:
            data = parse_analysis_log(md / "analysis.log")
            writer.writerow([
                md.name,
                data["carrier"],
                data["count"],
                data["volume"],
                data["ea"],
                data["d0"],
                data["sigma"],
                data["bulk"],
                data["shear"],
                data["young"],
                data["poisson"],
            ])

        fh.write("\nCoordination Numbers\n")
        fh.write("--------------------\n")
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["Run", "Temperature(K)", "Pair", "CN", "r_min(A)"])
        for md in md_dirs:
            for temp, pair, cn, r_min in parse_rdf_log(md / "rdf_process.log"):
                writer.writerow([md.name, temp, pair, cn, r_min])

    print(f"[INFO] Summary written to {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect LLZO pipeline outputs into summary.txt.")
    parser.add_argument("--root", default=str(ROOT), help="Folder containing MD_run_* outputs")
    args = parser.parse_args()
    write_summary(args.root)
