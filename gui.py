#!/usr/bin/env python3
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import yaml
except ImportError:
    yaml = None


ROOT = Path(__file__).resolve().parent
INPUT_PATH = ROOT / "input.yaml"


DEFAULTS = {
    "cif": "cubic-LLZO.cif",
    "output_dir": "./pipeline_runs",
    "supercell": [1, 1, 2],
    "dopants": [],
    "distance_filters": {
        "dop_dop_min": None,
        "dop_dop_max": None,
        "dop_ion_min": None,
        "dop_ion_max": 15,
        "ion_ion_min": None,
        "ion_ion_max": None,
    },
    "max_files_per_folder": 1000,
    "relax_model": 1,
    "md_temperatures": [600, 800, 900, 1000, 1200],
    "md_dump_pattern": "dump*{T}*",
    "run_rdf": True,
    "rdf_temperatures": [900],
    "rdf_pairs": "all",
    "rdf_rmax": 10.0,
    "rdf_dr": 0.05,
    "run_msd_arrhenius": True,
    "run_elastic": True,
    "run_trend_plots": True,
    "conductivity_t_ref": 300,
    "msd_fit_start": 100,
    "msd_fit_end": 200,
    "carrier_species": None,
    "stages": {
        "doping": True,
        "energy_comparison": True,
        "md": True,
        "post_processing": True,
        "rdf": True,
        "summary": True,
    },
}


DOPANT_COLUMNS = (
    ("dopant", "Dopant", 90, 10),
    ("dopant_valency", "Dopant valency", 120, 14),
    ("host", "Host", 90, 10),
    ("host_valency", "Host valency", 110, 12),
    ("count", "Count", 80, 8),
    ("carrier", "Carrier", 90, 10),
    ("carrier_valency", "Carrier valency", 120, 14),
)


def parse_scalar(text):
    text = str(text).strip()
    if text == "" or text.lower() == "null":
        return None
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def parse_list(text):
    if not str(text).strip():
        return []
    return [parse_scalar(x) for x in str(text).split(",") if x.strip()]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LLZO Pipeline")
        self.geometry("1050x720")
        self.log_queue = queue.Queue()
        self.proc = None

        self.vars = {}
        self.filter_enabled = {}
        self.stage_vars = {}
        self.dopant_rows = []

        self._build()
        self.load_existing_or_defaults()
        self.after(200, self.poll_log)

    def _var(self, name, value=""):
        v = tk.StringVar(value="" if value is None else str(value))
        self.vars[name] = v
        return v

    def _bool(self, name, value=False):
        v = tk.BooleanVar(value=bool(value))
        self.vars[name] = v
        return v

    def _build(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.build_structure_tab()
        self.build_dopants_tab()
        self.build_filters_tab()
        self.build_relax_md_tab()
        self.build_rdf_tab()
        self.build_analysis_tab()
        self.build_stages_tab()
        self.build_bottom()

    def build_structure_tab(self):
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="Structure")
        ttk.Label(frame, text="Input structure CIF").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self._var("cif"), width=70).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="Browse", command=self.pick_cif).grid(row=0, column=2)
        ttk.Label(frame, text="Output/run folder").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self._var("output_dir"), width=70).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="Browse", command=self.pick_output_dir).grid(row=1, column=2)
        for i, axis in enumerate("xyz"):
            ttk.Label(frame, text=f"Supercell {axis} multiplier").grid(row=i + 2, column=0, sticky="w", pady=6)
            ttk.Spinbox(frame, from_=1, to=20, textvariable=self._var(f"supercell_{axis}"), width=8).grid(row=i + 2, column=1, sticky="w", padx=8)
        ttk.Label(
            frame,
            text="Example: CIF = cubic-LLZO.cif, output/run folder = ./pipeline_runs, supercell = 1, 1, 2. The code stays here; run_*, MD_run_*, logs, RDF folders, and summary.txt are saved in the output folder.",
            foreground="#555",
            wraplength=850,
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(16, 0))
        frame.columnconfigure(1, weight=1)

    def build_dopants_tab(self):
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="Dopants")
        ttk.Label(
            frame,
            text="Add one row per substitution. All rows must use the same carrier. Example: Nb, 5, Zr, 4, 1, Li, 1 means replace one Zr4+ with Nb5+ and charge-balance using Li+.",
            foreground="#555",
            wraplength=930,
        ).grid(row=0, column=0, columnspan=7, sticky="w", pady=(0, 8))
        columns = tuple(spec[0] for spec in DOPANT_COLUMNS)
        self.dopant_tree = ttk.Treeview(frame, columns=columns, show="headings", height=10)
        for col, heading, width, _entry_width in DOPANT_COLUMNS:
            self.dopant_tree.heading(col, text=heading)
            self.dopant_tree.column(col, width=width, minwidth=width, anchor="center", stretch=False)
        self.dopant_tree.grid(row=1, column=0, columnspan=7, sticky="nsew")

        self.dopant_inputs = {}
        for i, (col, _heading, _width, entry_width) in enumerate(DOPANT_COLUMNS):
            v = tk.StringVar()
            self.dopant_inputs[col] = v
            ttk.Entry(frame, textvariable=v, width=entry_width).grid(row=2, column=i, padx=3, pady=8)
        for col, example in zip(columns, ("Nb", "5", "Zr", "4", "1", "Li", "1")):
            self.dopant_inputs[col].set(example)
        ttk.Button(frame, text="Add row", command=self.add_dopant_from_inputs).grid(row=3, column=0, sticky="w")
        ttk.Button(frame, text="Remove row", command=self.remove_dopant).grid(row=3, column=1, sticky="w")
        ttk.Label(
            frame,
            text="The boxes above line up with the table columns and are an editable example, not an active dopant. Press Add row to put it into the list.",
            foreground="#555",
        ).grid(row=4, column=0, columnspan=7, sticky="w", pady=(8, 0))
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

    def build_filters_tab(self):
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="Distance Filters")
        ttk.Label(
            frame,
            text="Distances are in Angstrom. Enable a field only when you want to reject structures outside that limit. Disabled means no limit.",
            foreground="#555",
            wraplength=860,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        names = ["dop_dop_min", "dop_dop_max", "dop_ion_min", "dop_ion_max", "ion_ion_min", "ion_ion_max"]
        for r, name in enumerate(names):
            enabled = tk.BooleanVar(value=False)
            self.filter_enabled[name] = enabled
            ttk.Checkbutton(frame, variable=enabled).grid(row=r + 1, column=0, sticky="w")
            ttk.Label(frame, text=f"{name} (Angstrom)").grid(row=r + 1, column=1, sticky="w", padx=8, pady=5)
            ttk.Entry(frame, textvariable=self._var(name), width=16).grid(row=r + 1, column=2, sticky="w")
        ttk.Label(
            frame,
            text="Example: dop_ion_max = 15 keeps only structures where every dopant-carrier distance is <= 15 Angstrom.",
            foreground="#555",
        ).grid(row=8, column=0, columnspan=3, sticky="w", pady=(12, 0))

    def build_relax_md_tab(self):
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="Relaxation & MD")
        ttk.Label(frame, text="ORB relaxation model").grid(row=0, column=0, sticky="w")
        model_values = [
            "1 - conservative inf OMAT",
            "2 - direct inf OMAT",
            "3 - conservative 20 OMAT",
            "4 - direct 20 OMAT",
            "5 - conservative inf MPA",
            "6 - direct inf MPA",
            "7 - conservative 20 MPA",
            "8 - direct 20 MPA",
        ]
        ttk.Combobox(frame, textvariable=self._var("relax_model"), values=model_values, width=34, state="readonly").grid(row=0, column=1, sticky="w")
        ttk.Label(frame, text="Max generated CIF files per dopant folder").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Spinbox(frame, from_=1, to=1000000, textvariable=self._var("max_files_per_folder"), width=12).grid(row=1, column=1, sticky="w")
        ttk.Label(frame, text="MD/RDF temperatures (K)").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self._var("md_temperatures"), width=40).grid(row=2, column=1, sticky="w")
        ttk.Label(frame, text="LAMMPS dump filename pattern").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self._var("md_dump_pattern"), width=40).grid(row=3, column=1, sticky="w")
        ttk.Label(
            frame,
            text="LAMMPS uses metal units: distance Angstrom, time ps, temperature K, energy eV. Example temperatures: 600, 800, 900. Pattern dump*{T}* searches for files such as dump_LLZO_900.lammpstrj.",
            foreground="#555",
            wraplength=860,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def build_rdf_tab(self):
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="RDF")
        ttk.Checkbutton(frame, text="Run RDF", variable=self._bool("run_rdf")).grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text="RDF temperatures (K)").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self._var("rdf_temperatures"), width=40).grid(row=1, column=1, sticky="w")
        ttk.Label(frame, text="RDF element pairs").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self._var("rdf_pairs"), width=40).grid(row=2, column=1, sticky="w")
        ttk.Label(frame, text="Maximum RDF radius rmax (Angstrom)").grid(row=3, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self._var("rdf_rmax"), width=12).grid(row=3, column=1, sticky="w")
        ttk.Label(frame, text="RDF bin width dr (Angstrom)").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self._var("rdf_dr"), width=12).grid(row=4, column=1, sticky="w")
        ttk.Label(
            frame,
            text="RDF temperatures must be selected from the MD temperatures. Each temperature is saved separately, for example MD_run_1/rdf_900K/. Pair format for users is element names: all or Li-Li, Li-O. The pipeline maps elements to LAMMPS type numbers after element_list is generated.",
            foreground="#555",
            wraplength=860,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def build_analysis_tab(self):
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="Analysis")
        ttk.Checkbutton(frame, text="MSD Arrhenius", variable=self._bool("run_msd_arrhenius")).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(frame, text="Elastic", variable=self._bool("run_elastic")).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(frame, text="Trend plots", variable=self._bool("run_trend_plots")).grid(row=2, column=0, sticky="w")
        fields = ["conductivity_t_ref", "msd_fit_start", "msd_fit_end", "carrier_species"]
        labels = {
            "conductivity_t_ref": "Conductivity reference temperature (K)",
            "msd_fit_start": "MSD fit start time (ps)",
            "msd_fit_end": "MSD fit end time (ps)",
            "carrier_species": "Carrier species, blank = auto (example Li or Na)",
        }
        for r, name in enumerate(fields, start=3):
            ttk.Label(frame, text=labels[name]).grid(row=r, column=0, sticky="w", pady=5)
            ttk.Entry(frame, textvariable=self._var(name), width=18).grid(row=r, column=1, sticky="w")
        ttk.Label(
            frame,
            text="MSD time is in ps. Diffusivity output is cm^2/s. Conductivity output is S/m.",
            foreground="#555",
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def build_stages_tab(self):
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="Stages")
        ttk.Label(frame, text="Disable stages only when rerunning part of an existing workflow.", foreground="#555").grid(row=0, column=0, sticky="w", pady=(0, 8))
        for r, name in enumerate(["doping", "energy_comparison", "md", "post_processing", "rdf", "summary"]):
            v = tk.BooleanVar(value=True)
            self.stage_vars[name] = v
            ttk.Checkbutton(frame, text=name, variable=v).grid(row=r + 1, column=0, sticky="w", pady=4)

    def build_bottom(self):
        bar = ttk.Frame(self, padding=(8, 0, 8, 8))
        bar.pack(fill="x")
        ttk.Button(bar, text="Save input.yaml", command=self.save_yaml).pack(side="left")
        ttk.Button(bar, text="Run pipeline", command=self.run_pipeline).pack(side="left", padx=8)
        self.status = ttk.Label(bar, text="Idle")
        self.status.pack(side="left", padx=8)
        ttk.Label(bar, text="Bottom panel: live pipeline log/output", foreground="#555").pack(side="left", padx=8)

        self.log = tk.Text(self, height=14, wrap="word")
        self.log.pack(fill="both", expand=False, padx=8, pady=(0, 8))

    def pick_cif(self):
        path = filedialog.askopenfilename(initialdir=ROOT, filetypes=[("CIF files", "*.cif"), ("All files", "*")])
        if path:
            try:
                self.vars["cif"].set(str(Path(path).resolve().relative_to(ROOT)))
            except ValueError:
                self.vars["cif"].set(path)

    def pick_output_dir(self):
        path = filedialog.askdirectory(initialdir=ROOT)
        if path:
            try:
                self.vars["output_dir"].set(str(Path(path).resolve().relative_to(ROOT)))
            except ValueError:
                self.vars["output_dir"].set(path)

    def add_dopant_from_inputs(self):
        values = [self.dopant_inputs[k].get().strip() for k in self.dopant_inputs]
        if not values[0] or not values[2]:
            messagebox.showerror("Dopants", "dopant and host are required")
            return
        self.dopant_tree.insert("", "end", values=values)

    def remove_dopant(self):
        for item in self.dopant_tree.selection():
            self.dopant_tree.delete(item)

    def load_existing_or_defaults(self):
        cfg = DEFAULTS
        if INPUT_PATH.exists() and yaml is not None:
            try:
                cfg = yaml.safe_load(INPUT_PATH.read_text()) or DEFAULTS
            except Exception:
                cfg = DEFAULTS
        self.apply_config(cfg)

    def apply_config(self, cfg):
        self.vars["cif"].set(cfg.get("cif", DEFAULTS["cif"]))
        self.vars["output_dir"].set(cfg.get("output_dir", DEFAULTS["output_dir"]))
        for axis, value in zip("xyz", cfg.get("supercell", DEFAULTS["supercell"])):
            self.vars[f"supercell_{axis}"].set(value)
        for row in self.dopant_tree.get_children():
            self.dopant_tree.delete(row)
        for d in cfg.get("dopants", DEFAULTS["dopants"]):
            self.dopant_tree.insert("", "end", values=[d.get(k, "") for k in ("dopant", "dopant_valency", "host", "host_valency", "count", "carrier", "carrier_valency")])
        for name, value in (cfg.get("distance_filters") or {}).items():
            if name in self.vars:
                self.vars[name].set("" if value is None else value)
                self.filter_enabled[name].set(value is not None)
        for name in ["max_files_per_folder", "md_dump_pattern", "rdf_rmax", "rdf_dr", "conductivity_t_ref", "msd_fit_start", "msd_fit_end"]:
            self.vars[name].set(cfg.get(name, DEFAULTS[name]))
        relax_value = str(cfg.get("relax_model", DEFAULTS["relax_model"]))
        model_labels = [
            "1 - conservative inf OMAT",
            "2 - direct inf OMAT",
            "3 - conservative 20 OMAT",
            "4 - direct 20 OMAT",
            "5 - conservative inf MPA",
            "6 - direct inf MPA",
            "7 - conservative 20 MPA",
            "8 - direct 20 MPA",
        ]
        self.vars["relax_model"].set(next((m for m in model_labels if m.startswith(relax_value.split()[0] + " ")), model_labels[0]))
        self.vars["md_temperatures"].set(", ".join(map(str, cfg.get("md_temperatures", DEFAULTS["md_temperatures"]))))
        self.vars["rdf_temperatures"].set(", ".join(map(str, cfg.get("rdf_temperatures", DEFAULTS["rdf_temperatures"]))))
        self.vars["rdf_pairs"].set("all" if cfg.get("rdf_pairs", "all") == "all" else ", ".join(cfg["rdf_pairs"]))
        self.vars["carrier_species"].set("" if cfg.get("carrier_species") is None else cfg.get("carrier_species"))
        for name in ["run_rdf", "run_msd_arrhenius", "run_elastic", "run_trend_plots"]:
            self.vars[name].set(bool(cfg.get(name, DEFAULTS[name])))
        for name, v in self.stage_vars.items():
            v.set(bool((cfg.get("stages") or DEFAULTS["stages"]).get(name, True)))

    def collect_config(self):
        dopants = []
        carriers = set()
        for item in self.dopant_tree.get_children():
            vals = self.dopant_tree.item(item, "values")
            d = {
                "dopant": vals[0],
                "dopant_valency": int(vals[1]),
                "host": vals[2],
                "host_valency": int(vals[3]),
                "count": int(vals[4]),
                "carrier": vals[5],
                "carrier_valency": int(vals[6]),
            }
            if d["dopant"] == d["host"]:
                raise ValueError("dopant and host must be different")
            dopants.append(d)
            carriers.add(d["carrier"])
        if not dopants:
            raise ValueError("At least one dopant row is required")
        if len(carriers) != 1:
            raise ValueError("All dopant rows must share the same carrier")
        if not self.vars["output_dir"].get().strip():
            raise ValueError("Choose an output/run folder")

        filters = {}
        for name, enabled in self.filter_enabled.items():
            filters[name] = parse_scalar(self.vars[name].get()) if enabled.get() else None

        rdf_pairs_raw = self.vars["rdf_pairs"].get().strip()
        rdf_pairs = "all" if rdf_pairs_raw.lower() == "all" else [x.strip() for x in rdf_pairs_raw.split(",") if x.strip()]
        md_temperatures = [int(x) for x in parse_list(self.vars["md_temperatures"].get())]
        rdf_temperatures = [int(x) for x in parse_list(self.vars["rdf_temperatures"].get())]
        if bool(self.vars["run_rdf"].get()):
            if not rdf_temperatures:
                raise ValueError("Enter at least one RDF temperature")
            invalid = sorted(set(rdf_temperatures) - set(md_temperatures))
            if invalid:
                raise ValueError(f"RDF temperatures must be chosen from MD temperatures. Invalid: {invalid}")
            if rdf_pairs != "all":
                bad_pairs = [
                    p for p in rdf_pairs
                    if len(p.split("-")) != 2 or not all(part.isalpha() for part in p.split("-"))
                ]
                if bad_pairs:
                    raise ValueError(f"RDF pairs must use element names like Li-Li or Li-O, not type numbers. Invalid: {bad_pairs}")

        return {
            "cif": self.vars["cif"].get().strip(),
            "output_dir": self.vars["output_dir"].get().strip(),
            "supercell": [int(self.vars[f"supercell_{a}"].get()) for a in "xyz"],
            "dopants": dopants,
            "distance_filters": filters,
            "max_files_per_folder": int(self.vars["max_files_per_folder"].get()),
            "relax_model": int(str(self.vars["relax_model"].get()).split()[0]),
            "md_temperatures": md_temperatures,
            "md_dump_pattern": self.vars["md_dump_pattern"].get().strip(),
            "run_rdf": bool(self.vars["run_rdf"].get()),
            "rdf_temperatures": rdf_temperatures,
            "rdf_pairs": rdf_pairs,
            "rdf_rmax": float(self.vars["rdf_rmax"].get()),
            "rdf_dr": float(self.vars["rdf_dr"].get()),
            "run_msd_arrhenius": bool(self.vars["run_msd_arrhenius"].get()),
            "run_elastic": bool(self.vars["run_elastic"].get()),
            "run_trend_plots": bool(self.vars["run_trend_plots"].get()),
            "conductivity_t_ref": int(self.vars["conductivity_t_ref"].get()),
            "msd_fit_start": float(self.vars["msd_fit_start"].get()),
            "msd_fit_end": float(self.vars["msd_fit_end"].get()),
            "carrier_species": parse_scalar(self.vars["carrier_species"].get()),
            "stages": {name: bool(v.get()) for name, v in self.stage_vars.items()},
        }

    def save_yaml(self):
        if yaml is None:
            messagebox.showerror("Missing dependency", "PyYAML is required: pip install pyyaml")
            return False
        try:
            cfg = self.collect_config()
            INPUT_PATH.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            self.status.config(text="Saved")
            return True
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return False

    def run_pipeline(self):
        if self.proc is not None:
            messagebox.showinfo("Pipeline", "Pipeline is already running")
            return
        if not self.save_yaml():
            return
        self.status.config(text="Running")
        self.log.delete("1.0", "end")
        thread = threading.Thread(target=self._run_pipeline_thread, daemon=True)
        thread.start()

    def _run_pipeline_thread(self):
        cmd = [sys.executable, str(ROOT / "pipeline_runner.py"), "--input", str(INPUT_PATH)]
        self.proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.log_queue.put(line)
        rc = self.proc.wait()
        self.proc = None
        self.log_queue.put(f"\n[GUI] pipeline exited with code {rc}\n")
        self.log_queue.put(("__STATUS__", "Done" if rc == 0 else "Failed"))

    def poll_log(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                if isinstance(item, tuple) and item[0] == "__STATUS__":
                    self.status.config(text=item[1])
                else:
                    self.log.insert("end", item)
                    self.log.see("end")
        except queue.Empty:
            pass
        self.after(200, self.poll_log)


if __name__ == "__main__":
    App().mainloop()
