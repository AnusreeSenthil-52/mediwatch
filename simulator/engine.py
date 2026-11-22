"""
Block 3 - Central system, Block 4 - Warning score,
Block 5a - Check the present (rule engine), Block 5b - Look ahead (predictor).

Listens to every reading on MQTT, and once per simulated second (on each
ward/clock message) works out each bed's NEWS2, checks the rules, runs the
look-ahead, sends actuator commands and publishes a status for the dashboard.

Run:  python -m simulator.engine --config config/ward_config.json
"""
import argparse
import json
import queue
from collections import defaultdict, deque

from .common import load_json, make_mqtt_client, publish
from .database import Database
from .news2 import news2
from .predictor import look_ahead
from .ml_risk import SyntheticRiskClassifier

VITALS = ["hr", "spo2", "rr", "sbp", "temp", "consciousness"]
# Used for a vital that has no sensor attached in the setup window (scores 0)
NOT_MONITORED = {"hr": 75, "spo2": 98, "rr": 15, "sbp": 125, "temp": 36.8, "consciousness": "A"}


class BedState:
    def __init__(self, cfg):
        self.cfg = cfg
        self.id = cfg["id"]
        self.latest = {}                     # sensor -> (t, value)
        self.history = deque()               # (t, vitals) for the look-ahead
        self.cmd = {a: False for a in cfg["actuators"]}      # what the engine asked for
        self.actual = {}                                    # what the ward reports is on
        self.emergency = False               # 6a in progress
        self.early = False                   # 6b in progress
        self.next_predict = 0
        self.prediction = None
        self.last_choice = None
        self.calm_since = None
        self.severity = None                 # hidden truth, logged only
        self.manual_active = False           # user injected manual readings (Patient Lab)
        self.sensor_faults = {}              # sensor -> active injected fault
        self.fault_started = {}
        self.detected_faults = set()
        self.invalid_sensors = set()
        self.raw_windows = defaultdict(lambda: deque(maxlen=5))


class Engine:
    def __init__(self, ward_cfg, rules, care):
        self.cfg, self.rules, self.care = ward_cfg, rules, care
        self.mode = ward_cfg["mode"]
        self.beds = {b["id"]: BedState(b) for b in ward_cfg["beds"]}
        self.db = Database()
        self.db.start_run(self.mode, ward_cfg)
        self.ml_model = SyntheticRiskClassifier()
        mq = ward_cfg.get("mqtt", {})
        self.client = make_mqtt_client("engine", mq.get("host", "localhost"), mq.get("port", 1883))
        self.inbox = queue.Queue()
        self.client.on_message = lambda c, u, m: self.inbox.put((m.topic, json.loads(m.payload)))
        for topic in ["ward/+/vitals/+", "ward/+/actuators", "ward/+/truth", "ward/+/manual_vitals",
                      "ward/+/sensor_fault_state", "ward/clock", "ward/control"]:
            self.client.subscribe(topic)

    # ---------- outputs ----------
    def event(self, bed, t, kind, text):
        publish(self.client, f"ward/{bed.id}/event", {"t": t, "kind": kind, "text": text})
        self.db.decision(bed.id, t, kind, text)
        print(f"[engine] t={t:>4} {bed.id}: {text}")

    def set_actuator(self, bed, name, on, reason, t):
        if name not in bed.cmd or bed.cmd[name] == on:
            return
        bed.cmd[name] = on
        publish(self.client, f"ward/{bed.id}/cmd", {"actuator": name, "on": on, "reason": reason})
        self.db.action(bed.id, t, name, on, reason)

    # ---------- the once-per-second cycle ----------
    def evaluate(self, bed, t):
        r = self.rules
        missing = [k for k in bed.cfg["sensors"] if k not in bed.latest]
        stale = [k for k, (tt, _) in bed.latest.items() if t - tt > r["stale_reading_s"]]
        blocked_faults = {k: f for k, f in bed.sensor_faults.items()
                          if f in ("disconnected", "communication_dropout", "frozen", "invalid")}
        for sensor_name, fault_name in blocked_faults.items():
            last_t = bed.latest.get(sensor_name, (bed.fault_started.get(sensor_name, t), None))[0]
            detected = t - last_t > r["stale_reading_s"]
            if fault_name == "frozen":
                samples = bed.raw_windows.get(sensor_name, [])
                detected = len(samples) >= 5 and len(set(samples)) == 1
            if detected and sensor_name not in bed.detected_faults:
                bed.detected_faults.add(sensor_name)
                reason = ("five consecutive identical samples" if fault_name == "frozen"
                          else f"no trustworthy fresh reading for more than {r['stale_reading_s']} simulated seconds")
                self.event(bed, t, "sensor_fault_detected",
                           f"{sensor_name.upper()} {fault_name.replace('_', ' ')} detected: {reason}")
        unavailable = sorted(set(missing + stale + list(bed.invalid_sensors) + list(blocked_faults)))
        if unavailable:
            publish(self.client, f"ward/{bed.id}/status", {
                "bed": bed.id, "t": t, "waiting_for": missing, "stale": stale,
                "invalid": sorted(bed.invalid_sensors), "sensor_faults": bed.sensor_faults,
                "monitoring_incomplete": True,
                "monitoring_message": "Patient score and prediction paused because one or more configured sensor readings are unavailable or invalid."
            })
            return

        v = {k: bed.latest[k][1] if k in bed.latest else NOT_MONITORED[k] for k in VITALS}
        # During a noisy-sensor test, use a rolling median of the latest five raw samples.
        for k, fault in bed.sensor_faults.items():
            if fault == "noisy" and k in bed.raw_windows and bed.raw_windows[k]:
                vals = sorted(bed.raw_windows[k])
                v[k] = vals[len(vals)//2]
        v["on_oxygen"] = bed.actual.get("oxygen", False)    # use the valve's real state, in step with readings
        score, band, parts = news2(v)
        ml_risk = self.ml_model.predict(v, score)
        physiology_score = score - parts["oxygen"]
        self.db.score(bed.id, t, score, band, parts, bed.severity)

        bed.history.append((t, {k: v[k] for k in ["hr", "rr", "spo2", "sbp", "temp"]}))
        while bed.history and bed.history[0][0] < t - r["predict_history_s"]:
            bed.history.popleft()

        # ---- 5a: is the patient already in danger? ----
        if score >= r["emergency_threshold"] and not bed.emergency:
            bed.emergency = True
            bed.calm_since = None
            self.event(bed, t, "emergency", f"NEWS2 {score} is in the danger zone - emergency response")
            # Emergency response: alert both the emergency team and the nurse,
            # and temporarily increase sensor sampling for closer monitoring.
            for a in ["alarm", "oxygen", "bed_motor", "nurse_call"]:
                self.set_actuator(bed, a, True, "6a emergency", t)
            publish(self.client, f"ward/{bed.id}/sensor_cfg", {"interval_s": 1})
            self.event(
                bed, t, "intervention",
                "Emergency intervention: alarm active, nurse called, oxygen on, bed raised, closer monitoring enabled"
            )

        # ---- 5a-urgent: manual test readings that are red-flag but below the emergency score ----
        # NEWS2 says a score of 5-6, or any single parameter scoring 3, needs an urgent
        # clinical response. The dashboard already shows these as risky, so act on them too
        # (nurse + oxygen) rather than only watching. Limited to Patient Lab readings so
        # normal reactive/predictive comparison runs are unchanged.
        if (bed.manual_active and not bed.emergency and not bed.early
                and (score >= r.get("urgent_threshold", 5) or band in ("medium", "low-medium"))):
            bed.early = True
            bed.calm_since = None
            self.event(bed, t, "urgent", f"NEWS2 {score} ({band}) - urgent response")
            self.set_actuator(bed, "nurse_call", True, "urgent response", t)
            if parts["spo2"] > 0 or parts["rr"] > 0:
                self.set_actuator(bed, "oxygen", True, "urgent response", t)
            publish(self.client, f"ward/{bed.id}/sensor_cfg", {"interval_s": 1})
            self.event(bed, t, "intervention", "Urgent intervention: nurse called, oxygen on where needed, closer monitoring enabled")

        # ---- 5b: is the patient heading for danger? ----
        intervening = bed.emergency or bed.early
        enough_history = len(bed.history) >= 0.8 * r["predict_history_s"]
        if not intervening and enough_history and t >= bed.next_predict:
            bed.next_predict = t + r["predict_every_s"]
            bed.prediction = look_ahead(list(bed.history), bed.actual.get("oxygen", False),
                                        bed.actual.get("bed_motor", False), self.care, r)
            p = bed.prediction
            if self.mode == "predictive" and p["heading_for_danger"]:
                self.db.decision(bed.id, t, "prediction", p)
                if p["choice"] != bed.last_choice:
                    self.event(bed, t, "prediction",
                               f"Heading for NEWS2 {p['predicted_max_score']} in ~{p['danger_in_s']}s; "
                               "option costs: " + ", ".join(f"{o.replace('_', ' ')} {c}" for o, c in p["costs"].items())
                               + f". Chose {p['choice'].replace('_', ' ')}")
                if p["choice"] == "help_now":
                    bed.early = True
                    bed.calm_since = None
                    self.set_actuator(bed, "oxygen", True, "6b early intervention", t)
                    self.set_actuator(bed, "nurse_call", True, "6b early intervention", t)
                    publish(self.client, f"ward/{bed.id}/sensor_cfg", {"interval_s": 1})
                    self.event(bed, t, "early", "Early intervention: oxygen on, nurse called, closer monitoring")
            bed.last_choice = p["choice"] if p["heading_for_danger"] else None
        elif intervening:
            bed.prediction = None

        # ---- 7: patient responds -> stand down once settled ----
        if intervening:
            if physiology_score <= r["all_clear_score"]:
                bed.calm_since = bed.calm_since if bed.calm_since is not None else t
                if t - bed.calm_since >= r["all_clear_hold_s"]:
                    for a in list(bed.cmd):
                        self.set_actuator(bed, a, False, "all clear", t)
                    publish(self.client, f"ward/{bed.id}/sensor_cfg", {"reset": True})
                    bed.emergency = bed.early = False
                    bed.manual_active = False
                    bed.next_predict = t + r["predict_history_s"]
                    bed.history.clear()
                    self.event(bed, t, "recovered", "Readings back to normal - interventions stood down")
            else:
                bed.calm_since = None

        state = "emergency" if bed.emergency else "early" if bed.early else "normal"
        publish(self.client, f"ward/{bed.id}/status", {
            "bed": bed.id, "name": bed.cfg["name"], "age": bed.cfg["age"],
            "condition": bed.cfg["condition"], "t": t, "mode": self.mode,
            "vitals": {k: v[k] for k in VITALS},
            "raw_vitals": {k: bed.latest[k][1] if k in bed.latest else None for k in VITALS},
            "on_oxygen": v["on_oxygen"],
            "score": score, "band": band, "parts": parts, "state": state,
            "ml_risk": ml_risk, "stale": stale, "prediction": bed.prediction,
            "sensor_faults": bed.sensor_faults, "invalid": sorted(bed.invalid_sensors),
            "monitoring_incomplete": False,
        })

    # ---------- main loop ----------
    def run(self):
        self.client.loop_start()
        print(f"[engine] mode={self.mode}, run_id={self.db.run_id}")
        while True:
            topic, data = self.inbox.get()
            parts = topic.split("/")
            if topic == "ward/control":
                if data.get("state") in ("finished", "stopped"):
                    self.db.commit()
                    print("[engine] run stopped/completed; data saved to sim.db")
                    break
                continue
            if topic == "ward/clock":
                for bed in self.beds.values():
                    self.evaluate(bed, data["t"])
                self.db.commit()
                continue
            bed = self.beds.get(parts[1])
            if bed is None:
                continue
            if parts[2] == "sensor_fault_state":
                sensor_name = data.get("sensor")
                if data.get("active"):
                    bed.sensor_faults[sensor_name] = data.get("fault")
                    bed.fault_started[sensor_name] = data.get("t", 0)
                    bed.detected_faults.discard(sensor_name)
                    self.db.decision(bed.id, data.get("t", 0), "sensor_fault",
                                     {"sensor": sensor_name, "fault": data.get("fault"), "status": "injected"})
                else:
                    bed.sensor_faults.pop(sensor_name, None)
                    bed.fault_started.pop(sensor_name, None)
                    bed.detected_faults.discard(sensor_name)
                    bed.invalid_sensors.discard(sensor_name)
                    self.db.decision(bed.id, data.get("t", 0), "sensor_recovered",
                                     {"sensor": sensor_name, "status": "restored"})
                    bed.raw_windows[sensor_name].clear()
            elif parts[2] == "manual_vitals":
                if not data.get("clear"):
                    bed.manual_active = True
                    bed.calm_since = None        # fresh stimulus: restart the all-clear timer
            elif parts[2] == "vitals":
                sensor_name = parts[3]
                value = data.get("value")
                limits = {"hr": (20, 250), "spo2": (50, 100), "rr": (2, 70),
                          "sbp": (40, 250), "temp": (25, 45)}
                valid = True
                if sensor_name in limits:
                    try:
                        numeric = float(value)
                        lo, hi = limits[sensor_name]
                        valid = lo <= numeric <= hi
                    except (TypeError, ValueError):
                        valid = False
                elif sensor_name == "consciousness":
                    valid = str(value).upper() in {"A", "C", "V", "P", "U"}
                if not valid:
                    if sensor_name not in bed.invalid_sensors:
                        self.event(bed, data.get("t", 0), "sensor_invalid",
                                   f"{sensor_name.upper()} sensor sent an invalid reading; value rejected")
                    bed.invalid_sensors.add(sensor_name)
                else:
                    bed.invalid_sensors.discard(sensor_name)
                    bed.latest[sensor_name] = (data["t"], value)
                    if sensor_name in ("hr", "spo2", "rr", "sbp", "temp") and bed.sensor_faults.get(sensor_name) in ("noisy", "frozen"):
                        bed.raw_windows[sensor_name].append(float(value))
                    self.db.reading(bed.id, data["t"], sensor_name, value)
            elif parts[2] == "actuators":
                bed.actual = data
            elif parts[2] == "truth":
                bed.severity = data["severity"]
        self.client.loop_stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="ward_config.json")
    ap.add_argument("--mode", choices=["reactive", "predictive"], help="override the mode in the config")
    args = ap.parse_args()
    cfg = load_json(args.config)
    if args.mode:
        cfg["mode"] = args.mode
    Engine(cfg, load_json("rules.json"), load_json("scenarios.json")["care"]).run()


if __name__ == "__main__":
    main()
