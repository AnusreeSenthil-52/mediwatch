"""Virtual patient monitoring sensors with configurable fault injection."""
import random


class Sensor:
    def __init__(self, bed_id, kind, cfg, rng=None):
        self.bed_id = bed_id
        self.kind = kind
        self.interval_s = cfg["interval_s"]
        self.default_interval_s = cfg["interval_s"]
        self.noise = cfg["noise"]
        self.dropout = cfg["dropout"]
        self.rng = rng or random.Random()
        self.next_due = 0.0
        self.connected = True
        self.fault = None
        self.fault_until = None
        self.frozen_value = None

    @property
    def topic(self):
        return f"ward/{self.bed_id}/vitals/{self.kind}"

    def set_fault(self, fault, duration_s=None, t=0):
        self.fault = fault
        self.fault_until = (t + max(1, int(duration_s))) if duration_s else None
        self.frozen_value = None
        self.connected = fault != "disconnected"

    def clear_fault(self):
        self.fault = None
        self.fault_until = None
        self.frozen_value = None
        self.connected = True

    def read(self, t, true_vitals):
        if t < self.next_due:
            return None
        self.next_due = t + self.interval_s
        if self.fault == "disconnected" or not self.connected:
            return None
        if self.fault == "communication_dropout":
            return None  # sensor samples internally, but the simulated link loses the packet
        if self.rng.random() < self.dropout:
            return None
        if self.kind == "fall":
            value = int(bool(true_vitals.get("fall", False)))
        elif self.kind == "bed_occupancy":
            value = int(bool(true_vitals.get("bed_occupancy", True)))
        else:
            value = true_vitals[self.kind]
        if isinstance(value, (int, float)):
            if self.fault == "frozen":
                if self.frozen_value is None:
                    self.frozen_value = value
                value = self.frozen_value
            else:
                noise = self.noise * (5 if self.fault == "noisy" else 1)
                value = value + self.rng.gauss(0, noise)
            value = round(value, 1) if self.kind == "temp" else round(value)
            if self.fault == "invalid":
                value = {"spo2": 150, "hr": -10, "rr": 0, "sbp": 400, "temp": 150,
                         "consciousness": "X"}.get(self.kind, value)
            if self.kind == "spo2" and self.fault != "invalid":
                value = min(100, max(50, value))
        return value
