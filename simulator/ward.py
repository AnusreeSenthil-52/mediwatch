"""
The "physical world": virtual patients + their sensors + their actuators.

Talks to the rest of the system ONLY through MQTT:
  publishes  ward/<bed>/vitals/<sensor>   one reading
             ward/<bed>/actuators          actuator states when they change
             ward/<bed>/event              e.g. "nurse arrived"
             ward/clock                    simulated time, once per second
  listens    ward/<bed>/cmd                {"actuator": "oxygen", "on": true}
             ward/<bed>/sensor_cfg         {"interval_s": 1}  (closer monitoring)
                                           {"sensor": "spo2", "connected": false}  (probe off)
             ward/<bed>/inject             {"collapse": true}  (studio button)

Run:  python -m simulator.ward --config config/ward_config.json
"""
import argparse
import json
import queue
import random
import time

from .actuators import BedActuators
from .common import load_json, make_mqtt_client, publish
from .patient import PatientModel
from .sensors import Sensor


class Bed:
    def __init__(self, cfg, ward_cfg, scenarios, seed):
        self.id = cfg["id"]
        self.cfg = cfg
        rng = random.Random(seed)
        scenario = scenarios["scenarios"][cfg["scenario"]]
        self.patient = PatientModel(scenario, scenarios["care"], rng=rng)
        overrides = cfg.get("sensor_settings", {})          # per-bed device values from the studio
        self.sensors = [Sensor(self.id, k, {**ward_cfg["sensor_defaults"][k], **overrides.get(k, {})},
                               rng=random.Random(seed * 31 + i))
                        for i, k in enumerate(cfg["sensors"])]
        self.actuators = BedActuators(self.patient, cfg["actuators"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="ward_config.json")
    args = ap.parse_args()

    ward_cfg = load_json(args.config)
    scenarios = load_json("scenarios.json")
    seed = ward_cfg.get("seed", 1)
    beds = {b["id"]: Bed(b, ward_cfg, scenarios, seed + i) for i, b in enumerate(ward_cfg["beds"])}

    inbox = queue.Queue()   # MQTT thread -> main loop (keeps patient updates single-threaded)
    rules = load_json("rules.json")
    MANUAL_TIMEOUT_S = rules.get("manual_timeout_s", 180)    # safety net: untreated manual patient self-recovers
    MANUAL_RECOVER_S = rules.get("manual_recover_s", 60)     # time for a treated manual patient to return to normal

    def on_message(client, userdata, msg):
        inbox.put((msg.topic, json.loads(msg.payload)))

    mq = ward_cfg.get("mqtt", {})
    client = make_mqtt_client("ward", mq.get("host", "localhost"), mq.get("port", 1883))
    client.on_message = on_message
    client.subscribe("ward/+/cmd")
    client.subscribe("ward/+/sensor_cfg")
    client.subscribe("ward/+/inject")
    client.subscribe("ward/+/manual_vitals")
    client.subscribe("ward/admin")
    client.loop_start()

    speed = ward_cfg.get("speed", 1)
    duration = ward_cfg.get("duration_s", 900)
    publish(client, "ward/control", {"state": "started", "mode": ward_cfg["mode"]})
    for bed in beds.values():
        publish(client, f"ward/{bed.id}/actuators", bed.actuators.state)
    print(f"[ward] {len(beds)} beds, speed x{speed}, running {duration} simulated seconds")

    t = 0
    stop_requested = False
    while t < duration and not stop_requested:
        tick_start = time.time()

        # 1. apply any commands that arrived
        while not inbox.empty():
            topic, data = inbox.get()
            if topic == "ward/admin":
                if data.get("action") == "stop":
                    stop_requested = True
                continue
            bed = beds.get(topic.split("/")[1])
            if bed is None:
                continue
            if topic.endswith("/manual_vitals"):
                p = bed.patient
                if data.get("clear"):
                    p.clear_manual()
                    publish(client, f"ward/{bed.id}/event", {"t": t, "kind": "manual",
                                                             "text": "Manual readings cleared; patient back to simulated baseline"})
                    continue
                allowed = {"hr", "spo2", "rr", "sbp", "temp"}
                values = {k: float(v) for k, v in data.items() if k in allowed}
                if not values:
                    continue
                p.apply_manual(values, MANUAL_RECOVER_S)
                # If alerts are already active for this bed, the patient needs new help now.
                for act, who in (("nurse_call", "nurse"), ("alarm", "emergency")):
                    if bed.actuators.state.get(act):
                        p.call_help(who)
                publish(client, f"ward/{bed.id}/event", {"t": t, "kind": "manual",
                                                         "text": "Manual vital signs applied - patient now simulated from these values"})
            elif topic.endswith("/cmd"):
                if bed.actuators.handle(data["actuator"], bool(data["on"])):
                    publish(client, f"ward/{bed.id}/actuators", bed.actuators.state)
            elif topic.endswith("/inject"):
                bed.patient.force_collapse()
                publish(client, f"ward/{bed.id}/event", {"t": t, "kind": "emergency",
                                                         "text": "Sudden collapse triggered from the studio"})
            elif topic.endswith("/sensor_fault"):
                sensor_name = data.get("sensor")
                fault_name = data.get("fault")
                for sensor in bed.sensors:
                    if sensor.kind != sensor_name:
                        continue
                    if data.get("action") == "clear" or fault_name in (None, "none"):
                        sensor.clear_fault()
                        publish(client, f"ward/{bed.id}/sensor_fault_state",
                                {"sensor": sensor.kind, "fault": None, "active": False, "t": t, "status": "restored"})
                        publish(client, f"ward/{bed.id}/event",
                                {"t": t, "kind": "sensor_recovered", "sensor": sensor.kind,
                                 "text": f"{sensor.kind.upper()} sensor restored; waiting for a fresh valid reading"})
                    else:
                        allowed_faults = {"disconnected", "frozen", "noisy", "communication_dropout", "invalid"}
                        if fault_name not in allowed_faults:
                            continue
                        duration = data.get("duration_s")
                        sensor.set_fault(fault_name, duration, t)
                        publish(client, f"ward/{bed.id}/sensor_fault_state",
                                {"sensor": sensor.kind, "fault": fault_name, "active": True,
                                 "t": t, "until": sensor.fault_until})
                        publish(client, f"ward/{bed.id}/event",
                                {"t": t, "kind": "sensor_fault", "sensor": sensor.kind,
                                 "fault": fault_name,
                                 "text": f"{sensor.kind.upper()} sensor fault injected: {fault_name.replace('_', ' ')}"})
            elif topic.endswith("/sensor_cfg") and "connected" in data:
                for s in bed.sensors:
                    if s.kind == data.get("sensor"):
                        s.connected = bool(data["connected"])
                        state = "reattached" if s.connected else "disconnected"
                        publish(client, f"ward/{bed.id}/event", {"t": t, "kind": "info",
                                                                 "text": f"{s.kind} probe {state}"})
            elif topic.endswith("/sensor_cfg"):
                for s in bed.sensors:
                    if data.get("reset"):
                        s.interval_s = s.default_interval_s          # back to normal monitoring
                    elif s.kind != "consciousness":
                        s.interval_s = data["interval_s"]           # closer monitoring
                        s.next_due = min(s.next_due, t + s.interval_s)

        # 2. advance every patient by one second and publish due readings
        t += 1
        for bed in beds.values():
            p = bed.patient
            p.step(1.0)
            for when, who in p.arrivals:
                text = "Nurse arrived and is treating the patient" if who == "nurse" \
                    else "Emergency team arrived and is treating the patient"
                publish(client, f"ward/{bed.id}/event", {"t": when, "kind": "arrival", "text": text})
            p.arrivals.clear()
            # Safety net: a manual patient nobody treats still settles after a while.
            if p.manual_offsets and not p.treated and p.manual_since is not None \
                    and p.t - p.manual_since >= MANUAL_TIMEOUT_S:
                p.treated = True
                p.recovery_per_s = max(p.recovery_per_s, p.manual_recovery_per_s)
                p.manual_since = None
                publish(client, f"ward/{bed.id}/event", {"t": t, "kind": "manual",
                                                         "text": "No treatment for a long time; patient settling on their own"})
            truth = p.vitals()
            for sensor in bed.sensors:
                if sensor.fault and sensor.fault_until is not None and t >= sensor.fault_until:
                    expired_fault = sensor.fault
                    sensor.clear_fault()
                    publish(client, f"ward/{bed.id}/sensor_fault_state",
                            {"sensor": sensor.kind, "fault": None, "active": False, "t": t, "status": "restored"})
                    publish(client, f"ward/{bed.id}/event",
                            {"t": t, "kind": "sensor_recovered", "sensor": sensor.kind,
                             "text": f"{sensor.kind.upper()} sensor fault ({expired_fault.replace('_', ' ')}) ended; waiting for a fresh valid reading"})
                value = sensor.read(t, truth)
                if value is not None:
                    publish(client, sensor.topic, {"t": t, "value": value})
            # hidden severity, for analysis only (the engine never reads it)
            publish(client, f"ward/{bed.id}/truth", {"t": t, "severity": round(p.s, 4)})

        # 3. tell everyone one second has passed
        publish(client, "ward/clock", {"t": t})
        time.sleep(max(0.0, 1.0 / speed - (time.time() - tick_start)))

    publish(client, "ward/control", {"state": "stopped" if stop_requested else "finished", "t": t, "saved": True})
    time.sleep(0.5)
    client.loop_stop()
    print("[ward] finished")


if __name__ == "__main__":
    main()
