"""
Screen 1 - Setup window (Tkinter, comes with Python).

Choose beds and patients, attach sensors and actuators, set device values,
pick a scenario, save everything to config/ward_config.json and press Start.

Run:  python setup_window.py
"""
import json
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "config", "ward_config.json")
SENSORS = ["hr", "spo2", "rr", "sbp", "temp", "consciousness"]
ACTUATORS = ["alarm", "nurse_call", "oxygen", "bed_motor"]
with open(os.path.join(ROOT, "config", "scenarios.json"), encoding="utf-8") as f:
    SCENARIOS = list(json.load(f)["scenarios"])


class SetupWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ICU simulator - setup")
        with open(CONFIG, encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.bed_rows = []
        self._build_general()
        self._build_beds_frame()
        self._build_devices()
        self._build_buttons()
        self.set_bed_count(len(self.cfg["beds"]))

    # ---------- general settings ----------
    def _build_general(self):
        frm = ttk.LabelFrame(self, text="Run settings", padding=8)
        frm.pack(fill="x", padx=10, pady=6)
        self.n_beds = tk.IntVar(value=len(self.cfg["beds"]))
        ttk.Label(frm, text="Number of beds").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(frm, from_=1, to=12, width=5, textvariable=self.n_beds,
                    command=lambda: self.set_bed_count(self.n_beds.get())).grid(row=0, column=1, padx=6)
        self.mode = tk.StringVar(value=self.cfg["mode"])
        ttk.Label(frm, text="Mode").grid(row=0, column=2, padx=(20, 4))
        for i, m in enumerate(["reactive", "predictive"]):
            ttk.Radiobutton(frm, text=m, value=m, variable=self.mode).grid(row=0, column=3 + i)
        self.speed = tk.DoubleVar(value=self.cfg["speed"])
        ttk.Label(frm, text="Speed (x real time)").grid(row=0, column=5, padx=(20, 4))
        ttk.Spinbox(frm, from_=1, to=50, width=5, textvariable=self.speed).grid(row=0, column=6)
        self.duration = tk.IntVar(value=self.cfg["duration_s"])
        ttk.Label(frm, text="Duration (sim s)").grid(row=0, column=7, padx=(20, 4))
        ttk.Entry(frm, width=7, textvariable=self.duration).grid(row=0, column=8)

    # ---------- one row per bed ----------
    def _build_beds_frame(self):
        self.beds_frame = ttk.LabelFrame(self, text="Beds, patients, sensors and actuators", padding=8)
        self.beds_frame.pack(fill="both", expand=True, padx=10, pady=6)
        heads = ["Bed", "Name", "Age", "Condition", "Scenario"] + SENSORS + ACTUATORS
        for c, h in enumerate(heads):
            ttk.Label(self.beds_frame, text=h, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=c, padx=3)

    def set_bed_count(self, n):
        n = max(1, min(12, int(n)))
        while len(self.bed_rows) < n:
            i = len(self.bed_rows)
            saved = self.cfg["beds"][i] if i < len(self.cfg["beds"]) else {}
            self.bed_rows.append(self._make_row(i + 1, saved))
        while len(self.bed_rows) > n:
            for w in self.bed_rows.pop()["widgets"]:
                w.destroy()

    def _make_row(self, r, saved):
        f = self.beds_frame
        row = {"id": f"bed{r}", "widgets": []}
        row["name"] = tk.StringVar(value=saved.get("name", f"Patient {r}"))
        row["age"] = tk.IntVar(value=saved.get("age", 60))
        row["condition"] = tk.StringVar(value=saved.get("condition", "General ward"))
        row["scenario"] = tk.StringVar(value=saved.get("scenario", "stable"))
        widgets = [
            ttk.Label(f, text=f"bed{r}"),
            ttk.Entry(f, width=12, textvariable=row["name"]),
            ttk.Spinbox(f, from_=1, to=110, width=4, textvariable=row["age"]),
            ttk.Entry(f, width=14, textvariable=row["condition"]),
            ttk.Combobox(f, width=18, values=SCENARIOS, state="readonly", textvariable=row["scenario"]),
        ]
        row["sensors"], row["actuators"] = {}, {}
        for k in SENSORS:
            row["sensors"][k] = tk.BooleanVar(value=k in saved.get("sensors", SENSORS))
            widgets.append(ttk.Checkbutton(f, variable=row["sensors"][k]))
        for k in ACTUATORS:
            row["actuators"][k] = tk.BooleanVar(value=k in saved.get("actuators", ACTUATORS))
            widgets.append(ttk.Checkbutton(f, variable=row["actuators"][k]))
        for c, w in enumerate(widgets):
            w.grid(row=r, column=c, padx=3, pady=2)
        row["widgets"] = widgets
        return row

    # ---------- device values ----------
    def _build_devices(self):
        frm = ttk.LabelFrame(self, text="Device settings (all beds)", padding=8)
        frm.pack(fill="x", padx=10, pady=6)
        self.dev = {}
        for c, h in enumerate(["Sensor", "Reading interval (s)", "Noise (std dev)", "Dropout chance (0-1)"]):
            ttk.Label(frm, text=h, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=c, padx=6)
        for r, k in enumerate(SENSORS, start=1):
            d = self.cfg["sensor_defaults"][k]
            self.dev[k] = {f: tk.DoubleVar(value=d[f]) for f in ["interval_s", "noise", "dropout"]}
            ttk.Label(frm, text=k).grid(row=r, column=0, sticky="w")
            for c, f in enumerate(["interval_s", "noise", "dropout"], start=1):
                ttk.Entry(frm, width=8, textvariable=self.dev[k][f]).grid(row=r, column=c, padx=6, pady=1)

    def _build_buttons(self):
        frm = ttk.Frame(self, padding=8)
        frm.pack(fill="x", padx=10)
        ttk.Button(frm, text="Save config", command=self.save).pack(side="left")
        ttk.Button(frm, text="Save and start", command=self.start).pack(side="left", padx=8)

    # ---------- actions ----------
    def collect(self):
        cfg = dict(self.cfg)
        cfg["mode"] = self.mode.get()
        cfg["speed"] = float(self.speed.get())
        cfg["duration_s"] = int(self.duration.get())
        cfg["sensor_defaults"] = {k: {f: float(v.get()) for f, v in d.items()} for k, d in self.dev.items()}
        cfg["beds"] = []
        for row in self.bed_rows:
            sensors = [k for k, v in row["sensors"].items() if v.get()]
            if not sensors:
                raise ValueError(f"{row['id']} has no sensors attached")
            cfg["beds"].append({
                "id": row["id"], "name": row["name"].get(), "age": int(row["age"].get()),
                "condition": row["condition"].get(), "scenario": row["scenario"].get(),
                "sensors": sensors,
                "actuators": [k for k, v in row["actuators"].items() if v.get()],
            })
        return cfg

    def save(self):
        try:
            cfg = self.collect()
        except (ValueError, tk.TclError) as e:
            messagebox.showerror("Check the values", str(e))
            return False
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        self.cfg = cfg
        return True

    def start(self):
        if self.save():
            subprocess.Popen([sys.executable, os.path.join(ROOT, "run_all.py")], cwd=ROOT)
            messagebox.showinfo("Started", "Simulator started. The dashboard opens at http://localhost:8000")


if __name__ == "__main__":
    SetupWindow().mainloop()
