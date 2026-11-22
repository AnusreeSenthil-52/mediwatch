"""
Block 1 - Virtual patients (and block 7 - Patient responds).

Each patient has one hidden number, `severity` (0 = well, 1 = critically ill).
Every simulated second severity changes according to the scenario, and the
five vital signs are calculated from it. Actuators (oxygen, bed motor, nurse,
emergency team) change how severity moves - that is how the patient "responds".

The same class is reused by the predictor as a "digital twin" to test
what-if options, so keep it free of MQTT and printing.
"""
import random

# Average adult values when severity = 0, and how much each vital moves
# when severity goes from 0 to 1. The predictor uses these too.
POPULATION_BASELINE = {"hr": 75, "rr": 15, "spo2": 98, "sbp": 125, "temp": 36.8}
SLOPE = {"hr": 50, "rr": 14, "spo2": -10, "sbp": -35, "temp": 2.0}
OXYGEN_SPO2_BOOST = 4
BED_RAISED_RR_DROP = 2


class PatientModel:
    def __init__(self, scenario, care, rng=None, personal_variation=True):
        self.sc = scenario
        self.care = care
        self.rng = rng or random.Random()
        self.t = 0.0
        self.s = scenario["start_severity"]
        self.oxygen = False
        self.bed_raised = False
        self.treated = False          # True once a nurse/doctor has treated the cause
        self.recovery_per_s = 0.0
        self.pending_help = []        # list of (arrival_time, "nurse" | "emergency")
        self.arrivals = []            # filled when help arrives (read by ward.py for events)
        self.manual_offsets = {}      # vital -> amount the user-entered value differs from the model
        self.manual_s0 = 0.0          # severity when the manual values were entered
        self.manual_recovery_per_s = 0.0
        self.manual_since = None      # simulated time the manual values were entered

        # Every patient is slightly different from the average
        self.baseline = dict(POPULATION_BASELINE)
        if personal_variation:
            spread = {"hr": 6, "rr": 1.5, "spo2": 0.8, "sbp": 8, "temp": 0.2}
            for k, sd in spread.items():
                self.baseline[k] += self.rng.gauss(0, sd)
            self.baseline["spo2"] = min(self.baseline["spo2"], 99.5)

    # ---------- what the scenario wants ----------
    def scenario_drift(self):
        sc = self.sc
        if "collapse_at_s" in sc and self.t >= sc["collapse_at_s"]:
            return sc["collapse_drift"]
        return sc["drift_per_s"]

    # ---------- actuator effects ----------
    def call_help(self, who):
        delay = self.care["nurse_delay_s"] if who == "nurse" else self.care["emergency_delay_s"]
        self.pending_help.append((self.t + delay, who))

    def force_collapse(self):
        """Triggered from the studio: a new problem starts right now."""
        self.sc = dict(self.sc, collapse_at_s=self.t, collapse_drift=0.010)
        self.treated = False
        self.recovery_per_s = 0.0

    def _help_arrives(self, who):
        self.treated = True
        rate = self.care["nurse_recovery_per_s"] if who == "nurse" else self.care["emergency_recovery_per_s"]
        if self.manual_offsets:
            rate = max(rate, self.manual_recovery_per_s)    # manual test patients respond within ~1 min
        self.recovery_per_s = max(self.recovery_per_s, rate)
        self.arrivals.append((self.t, who))

    # ---------- one simulated step ----------
    def step(self, dt=1.0):
        self.t += dt
        for item in list(self.pending_help):
            if self.t >= item[0]:
                self.pending_help.remove(item)
                self._help_arrives(item[1])

        # Untreated illness gets worse faster the sicker the patient is
        drift = 0.0 if self.treated else self.scenario_drift() * (1 + 2 * self.s)
        if self.oxygen:
            drift *= 0.6
        noise = self.rng.gauss(0, self.sc.get("noise", 0.0)) if self.sc.get("noise") else 0.0
        self.s += (drift - self.recovery_per_s) * dt + noise * (dt ** 0.5)
        self.s = min(1.0, max(0.0, self.s))
        if self.manual_offsets and self.s <= 0.005:
            self.manual_offsets = {}                         # fully recovered: back to the normal model

    # ---------- manual vitals (Patient Lab) ----------
    def apply_manual(self, values, recover_s=60.0):
        """The user types vital signs. The patient really BECOMES that sick: severity is set
        from the values, and the vitals the user typed are held as offsets that fade as the
        patient is treated (oxygen, bed raise, nurse, emergency team) and severity falls."""
        cur = self._model_vitals()
        norm = []
        for k, val in values.items():
            if k in SLOPE:
                norm.append((val - self.baseline[k]) / SLOPE[k])
        s0 = min(0.8, max(0.3, max(norm))) if norm else self.s   # <0.85 keeps consciousness Alert
        self.s = s0
        self.manual_s0 = s0
        model = self._model_vitals()
        self.manual_offsets = {k: float(values.get(k, cur[k])) - model[k] for k in SLOPE}
        self.manual_recovery_per_s = s0 / recover_s
        self.treated = False
        self.recovery_per_s = 0.0
        self.pending_help.clear()
        self.manual_since = self.t

    def clear_manual(self):
        self.manual_offsets = {}
        self.s = min(self.s, self.sc["start_severity"])
        self.manual_since = None

    # ---------- what a perfect sensor would read ----------
    def vitals(self):
        out = self._model_vitals()
        if self.manual_offsets:
            f = min(1.0, self.s / self.manual_s0) if self.manual_s0 > 0 else 0.0
            for k, off in self.manual_offsets.items():
                out[k] += off * f
            out["spo2"] = min(100.0, out["spo2"])
        return out

    def _model_vitals(self):
        s, b = self.s, self.baseline
        spo2 = b["spo2"] + SLOPE["spo2"] * s + (OXYGEN_SPO2_BOOST if self.oxygen else 0)
        rr = b["rr"] + SLOPE["rr"] * s - (BED_RAISED_RR_DROP if self.bed_raised else 0)
        return {
            "hr": b["hr"] + SLOPE["hr"] * s,
            "rr": rr,
            "spo2": min(100.0, spo2),
            "sbp": b["sbp"] + SLOPE["sbp"] * s,
            "temp": b["temp"] + SLOPE["temp"] * s,
            "consciousness": "A" if s < 0.85 else "V",
        }
