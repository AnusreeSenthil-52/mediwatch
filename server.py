"""
ICU Simulation Studio - the server (FastAPI + WebSockets + MQTT).

* Serves the Wokwi-style studio at  http://localhost:8000
  and the simple ward dashboard at  http://localhost:8000/dashboard
* Subscribes to ward/# on the Mosquitto broker and pushes every message to
  the browser through a WebSocket, so the canvas wires light up live.
* Starts / stops the simulation processes (simulator.engine and
  simulator.ward) when you press Start / Stop in the studio.
* Reads results from sim.db (SQLite) for the Results tab.

Run:  python server.py
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager

import paho.mqtt.client as mqtt
import uvicorn
from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

import compare_runs
from simulator.common import CONFIG_DIR, ROOT, load_json

PY = sys.executable
CONFIG_PATH = os.path.join(CONFIG_DIR, "ward_config.json")

state = {"broker": False, "running": False, "stopping": False, "comparing": False, "mode": None}
procs = {}                                   # "engine" / "ward" -> subprocess.Popen
studio_clients, dash_clients = set(), set()  # open WebSockets
snapshot = {"status": {}, "actuators": {}, "events": [], "control": {}, "sensor_faults": {}}
LOOP = None
MQ = None


# ------------------------------------------------------------------ helpers
async def _send_all(clients, text):
    for ws in list(clients):
        try:
            await ws.send_text(text)
        except Exception:
            clients.discard(ws)


def push(obj, to_dashboard=None):
    """Send from any thread to every browser tab."""
    if LOOP is None:
        return
    asyncio.run_coroutine_threadsafe(_send_all(studio_clients, json.dumps(obj)), LOOP)
    if to_dashboard is not None:
        asyncio.run_coroutine_threadsafe(_send_all(dash_clients, json.dumps(to_dashboard)), LOOP)


def push_state():
    push({"type": "server", **state})


def results():
    """Last reactive run and last predictive run from sim.db."""
    import sqlite3
    if not os.path.exists(compare_runs.DB):
        return {"reactive": None, "predictive": None}
    conn = sqlite3.connect(compare_runs.DB)
    out = {}
    for mode in ("reactive", "predictive"):
        row = conn.execute("SELECT MAX(run_id) FROM runs WHERE mode=? AND run_id IN (SELECT DISTINCT run_id FROM scores)",
                           (mode,)).fetchone()
        if row and row[0]:
            _, rows = compare_runs.summary(conn, row[0])
            out[mode] = {"run_id": row[0], "rows": [dict(zip(
                ["bed", "peak", "red", "orange", "emergencies", "early", "emergency_at"], r)) for r in rows]}
        else:
            out[mode] = None
    conn.close()
    return out


# ------------------------------------------------------------------ MQTT bridge
def on_connect(client, userdata, flags, reason_code, properties):
    state["broker"] = not reason_code.is_failure
    client.subscribe("ward/#")
    push_state()


def on_disconnect(client, userdata, flags, reason_code, properties):
    state["broker"] = False
    push_state()


def on_message(client, userdata, msg):
    topic = msg.topic
    if topic.endswith("/truth"):
        return                                   # hidden severity: never shown to the user
    try:
        data = json.loads(msg.payload)
    except ValueError:
        return
    parts = topic.split("/")
    if topic == "ward/control":
        snapshot["control"] = data
        if data.get("state") == "started" and not state["comparing"]:
            snapshot.update(status={}, actuators={}, events=[], sensor_faults={})
            state.update(running=True, mode=data.get("mode"))
        elif data.get("state") in ("finished", "stopped") and not state["comparing"]:
            state["running"] = False
        push_state()
    if state["comparing"]:
        return                                   # comparison runs at 200x: don't flood the browser
    dash = None
    if len(parts) == 3 and parts[2] == "status":
        snapshot["status"][parts[1]] = data
        dash = {"type": "status", "bed": parts[1], "data": data}
    elif len(parts) == 3 and parts[2] == "actuators":
        snapshot["actuators"][parts[1]] = data
        dash = {"type": "actuators", "bed": parts[1], "data": data}
    elif len(parts) == 3 and parts[2] == "event":
        snapshot["events"] = (snapshot["events"] + [dict(data, bed=parts[1])])[-300:]
        dash = {"type": "event", "bed": parts[1], "data": data}
    elif len(parts) == 3 and parts[2] == "sensor_fault_state":
        key = f"{parts[1]}:{data.get('sensor')}"
        if data.get("active"):
            snapshot["sensor_faults"][key] = dict(data, bed=parts[1])
        else:
            snapshot["sensor_faults"].pop(key, None)
        dash = {"type": "sensor_fault_state", "bed": parts[1], "data": data}
    elif topic == "ward/control":
        dash = {"type": "control", "bed": "control", "data": data}
    push({"type": "mqtt", "topic": topic, "data": data}, {"type": "mqtt", "topic": topic, "data": data})


def start_mqtt():
    global MQ
    cfg = load_json("ward_config.json").get("mqtt", {})
    MQ = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="studio-server")
    MQ.on_connect, MQ.on_disconnect, MQ.on_message = on_connect, on_disconnect, on_message
    MQ.reconnect_delay_set(1, 5)
    MQ.connect_async(cfg.get("host", "localhost"), cfg.get("port", 1883))
    MQ.loop_start()                              # keeps retrying until Mosquitto is up


def watch_processes():
    """Notice when the ward process ends (run finished or crashed)."""
    while True:
        time.sleep(0.5)
        ward = procs.get("ward")
        if ward is not None and ward.poll() is not None:
            procs.pop("ward")
            time.sleep(2)
            eng = procs.pop("engine", None)
            if eng is not None and eng.poll() is None:
                eng.terminate()
            if state["running"]:
                state["running"] = False
                push_state()


def stop_processes():
    for name in ("ward", "engine"):
        p = procs.pop(name, None)
        if p is not None and p.poll() is None:
            p.terminate()


# ------------------------------------------------------------------ app
@asynccontextmanager
async def lifespan(app):
    global LOOP
    LOOP = asyncio.get_running_loop()
    start_mqtt()
    threading.Thread(target=watch_processes, daemon=True).start()
    yield
    stop_processes()
    MQ.loop_stop()


app = FastAPI(lifespan=lifespan)


@app.get("/")
def landing_page():
    return FileResponse(os.path.join(ROOT, "static", "landing.html"))


@app.get("/simulator")
def simulator_page():
    return FileResponse(os.path.join(ROOT, "static", "home.html"))


@app.get("/studio")
def original_studio_page():
    return FileResponse(os.path.join(ROOT, "static", "studio.html"))


@app.get("/api/state")
def api_state():
    return {"state": state, "snapshot": snapshot}


@app.get("/manual")
def manual_page():
    return FileResponse(os.path.join(ROOT, "static", "manual.html"))


@app.post("/api/manual-readings")
def manual_readings(body: dict = Body(...)):
    """Inject user-entered vital signs into the live engine via the same MQTT topics."""
    if not state["broker"] or MQ is None:
        return JSONResponse({"error": "Mosquitto is not connected. Start the broker first."}, status_code=409)
    bed_id = str(body.get("bed", ""))
    cfg = load_json("ward_config.json")
    beds = {str(b.get("id")) for b in cfg.get("beds", [])}
    if bed_id not in beds:
        return JSONResponse({"error": f"Unknown bed '{bed_id}'. Check the configured bed IDs."}, status_code=400)
    if not state["running"]:
        return JSONResponse({"error": "Start a simulation before applying readings."}, status_code=409)
    ranges = {
        "hr": (20, 250), "spo2": (50, 100), "rr": (1, 70),
        "sbp": (40, 250), "temp": (25, 45)
    }
    values = body.get("values", {})
    if not isinstance(values, dict) or not values:
        return JSONResponse({"error": "Provide at least one vital-sign value."}, status_code=400)
    sent = {}
    for sensor, limits in ranges.items():
        if sensor not in values or values[sensor] in (None, ""):
            continue
        try:
            value = float(values[sensor])
        except (TypeError, ValueError):
            return JSONResponse({"error": f"{sensor} must be numeric."}, status_code=400)
        if not limits[0] <= value <= limits[1]:
            return JSONResponse({"error": f"{sensor} must be between {limits[0]} and {limits[1]}."}, status_code=400)
        sent[sensor] = value
    if not sent:
        return JSONResponse({"error": "No valid vital-sign values were supplied."}, status_code=400)
    # The physical-world process applies overrides on every tick, so user-entered
    # values remain visible instead of being overwritten by the next synthetic sample.
    MQ.publish(f"ward/{bed_id}/manual_vitals", json.dumps(sent), qos=1)
    return {"ok": True, "bed": bed_id, "sent": sent,
            "message": "Manual readings applied to this virtual patient until changed or the run restarts."}


@app.post("/api/manual-readings/clear/{bed}")
def manual_clear(bed: str):
    """Stop overriding this bed's vitals: ramp back to the simulated patient."""
    if not state["broker"] or MQ is None:
        return JSONResponse({"error": "Mosquitto is not connected."}, status_code=409)
    MQ.publish(f"ward/{bed}/manual_vitals", json.dumps({"clear": True}), qos=1)
    return {"ok": True, "bed": bed}


@app.get("/dashboard")
def dashboard_page():
    return FileResponse(os.path.join(ROOT, "static", "dashboard.html"))


@app.get("/api/config")
def get_config():
    return load_json("ward_config.json")


@app.post("/api/config")
def save_config(cfg: dict = Body(...)):
    if state["running"] or state["stopping"]:
        return JSONResponse({"error": "Stop the simulation before changing the setup."}, status_code=409)
    beds = cfg.get("beds")
    if not isinstance(beds, list) or not beds:
        return JSONResponse({"error": "Add at least one bed."}, status_code=400)
    scenarios = load_json("scenarios.json")["scenarios"]
    for b in beds:
        if b.get("scenario") not in scenarios:
            return JSONResponse({"error": f"{b.get('id')}: unknown scenario"}, status_code=400)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return {"saved": True}


@app.get("/api/scenarios")
def get_scenarios():
    data = load_json("scenarios.json")
    # Keep the key list for the original Studio editor, and also expose the
    # full profile objects for the Ward Builder scenario library.
    profiles = data.get("scenarios", {})
    return {"scenarios": list(profiles.keys()), "profiles": profiles,
            "care": data.get("care", {}), "rules": load_json("rules.json")}


@app.post("/api/start")
async def start(body: dict = Body(default={})):
    if not state["broker"]:
        return JSONResponse({"error": "Cannot reach the Mosquitto broker on localhost:1883. Start Mosquitto first."},
                            status_code=409)
    if state["running"] or state["stopping"] or state["comparing"]:
        return JSONResponse({"error": "A simulation is already running."}, status_code=409)
    cfg = load_json("ward_config.json")
    mode = body.get("mode", cfg.get("mode", "predictive"))
    if mode not in ("reactive", "predictive"):
        return JSONResponse({"error": "Mode must be reactive or predictive."}, status_code=400)
    cfg["mode"] = mode
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    stop_processes()
    procs["engine"] = subprocess.Popen([PY, "-m", "simulator.engine", "--mode", mode], cwd=ROOT)
    await asyncio.sleep(1.0)                     # let the engine subscribe before readings start
    procs["ward"] = subprocess.Popen([PY, "-m", "simulator.ward"], cwd=ROOT)
    state.update(running=True, mode=mode)
    push_state()
    return {"started": True, "mode": mode}


@app.post("/api/stop")
def stop():
    """Gracefully stop the virtual ward and commit the partial run to SQLite."""
    if not state["running"] and not state["stopping"]:
        return {"stopped": True, "already_stopped": True, "saved": True}
    state["stopping"] = True
    push_state()
    if MQ is not None and state["broker"]:
        MQ.publish("ward/admin", json.dumps({"action": "stop"}), qos=1)
    # Give the ward time to publish its final control message and the engine
    # time to commit the current run before falling back to process termination.
    deadline = time.time() + 8
    while time.time() < deadline:
        ward = procs.get("ward")
        eng = procs.get("engine")
        if (ward is None or ward.poll() is not None) and (eng is None or eng.poll() is not None):
            break
        time.sleep(0.1)
    stop_processes()
    state["running"] = False
    state["stopping"] = False
    push_state()
    push({"type": "mqtt", "topic": "studio/info", "data": {"text": "Simulation stopped. All readings and events up to this point were saved."}})
    return {"stopped": True, "saved": True}


@app.post("/api/inject/{bed}")
def inject(bed: str):
    if not state["broker"] or MQ is None:
        return JSONResponse({"error": "Mosquitto is not connected."}, status_code=409)
    cfg = load_json("ward_config.json")
    if bed not in {str(b.get("id")) for b in cfg.get("beds", [])}:
        return JSONResponse({"error": f"Unknown bed {bed}."}, status_code=404)
    MQ.publish(f"ward/{bed}/inject", json.dumps({"collapse": True}), qos=1)
    return {"ok": True, "bed": bed, "message": "Collapse trigger sent to virtual patient."}


@app.post("/api/probe/{bed}/{sensor}")
def probe(bed: str, sensor: str, body: dict = Body(...)):
    if not state["broker"] or MQ is None:
        return JSONResponse({"error": "Mosquitto is not connected."}, status_code=409)
    MQ.publish(f"ward/{bed}/sensor_cfg", json.dumps({"sensor": sensor, "connected": bool(body.get("connected"))}), qos=1)
    return {"ok": True}


@app.get("/api/sensor-faults")
def get_sensor_faults():
    return {"active": list(snapshot.get("sensor_faults", {}).values()),
            "events": [e for e in snapshot.get("events", []) if str(e.get("kind", "")).startswith("sensor_")][-100:]}


@app.post("/api/sensor-fault")
def apply_sensor_fault(body: dict = Body(...)):
    if not state["broker"] or MQ is None:
        return JSONResponse({"error": "Mosquitto is not connected. Start Mosquitto first."}, status_code=409)
    if not state["running"]:
        return JSONResponse({"error": "Start the simulation before applying a sensor fault."}, status_code=409)
    bed_id = str(body.get("bed", ""))
    sensor = str(body.get("sensor", ""))
    fault = body.get("fault")
    action = body.get("action", "apply")
    cfg = load_json("ward_config.json")
    bed_cfg = next((b for b in cfg.get("beds", []) if str(b.get("id")) == bed_id), None)
    if bed_cfg is None:
        return JSONResponse({"error": f"Unknown bed {bed_id}."}, status_code=404)
    if sensor not in bed_cfg.get("sensors", []):
        return JSONResponse({"error": f"{sensor} is not configured for {bed_id}."}, status_code=400)
    if action == "clear":
        payload = {"action": "clear", "sensor": sensor}
    else:
        allowed = {"disconnected", "frozen", "noisy", "communication_dropout", "invalid"}
        if fault not in allowed:
            return JSONResponse({"error": "Unsupported sensor fault type."}, status_code=400)
        duration = body.get("duration_s")
        if duration is not None:
            try:
                duration = int(duration)
                if duration < 1 or duration > 3600:
                    raise ValueError()
            except (TypeError, ValueError):
                return JSONResponse({"error": "Fault duration must be between 1 and 3600 simulated seconds."}, status_code=400)
        payload = {"action": "apply", "sensor": sensor, "fault": fault, "duration_s": duration}
    MQ.publish(f"ward/{bed_id}/sensor_fault", json.dumps(payload), qos=1)
    return {"ok": True, "bed": bed_id, "sensor": sensor, "fault": fault if action != "clear" else None,
            "action": action, "message": "Sensor fault command sent to the running virtual ward."}


@app.get("/api/results")
def get_results():
    return results()


@app.get("/api/compare-status")
def compare_status():
    return {"running": bool(state["comparing"]), "mode": state["comparing"] or None, "results": results() if not state["comparing"] else None}


@app.post("/api/compare")
def compare():
    if state["running"] or state["stopping"] or state["comparing"]:
        return JSONResponse({"error": "Wait for the current run to finish."}, status_code=409)
    if not state["broker"]:
        return JSONResponse({"error": "Start Mosquitto first."}, status_code=409)

    def job():
        error = None
        try:
            cfg = load_json("ward_config.json")
            cfg["speed"] = 200
            path = os.path.join(CONFIG_DIR, "_compare.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            for mode in ("reactive", "predictive"):
                state["comparing"] = mode
                push_state()
                completed = subprocess.run(
                    [PY, "run_all.py", "--config", path, "--mode", mode, "--headless"],
                    cwd=ROOT, timeout=max(60, int(cfg.get("duration_s", 900) / 20) + 30),
                    capture_output=True, text=True
                )
                if completed.returncode != 0:
                    error = (completed.stderr or completed.stdout or f"{mode} comparison failed").strip()[-1200:]
                    break
        except Exception as exc:
            error = str(exc)
        finally:
            state["comparing"] = False
            push_state()
            payload = {"type": "results", **results()}
            if error:
                payload["error"] = error
            push(payload)

    threading.Thread(target=job, daemon=True).start()
    return {"started": True}


@app.get("/api/analytics")
def api_analytics():
    """Persistent run summaries and per-bed trends from the SQLite simulation log."""
    import sqlite3
    db_path = compare_runs.DB
    if not os.path.exists(db_path):
        return {"runs": [], "latest": None, "beds": [], "events": []}
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    runs = [dict(r) for r in conn.execute("SELECT run_id, mode, started, config FROM runs ORDER BY run_id DESC LIMIT 30")]
    for r in runs:
        try: r["config"] = json.loads(r["config"] or "{}")
        except Exception: r["config"] = {}
    latest = runs[0] if runs else None
    beds=[]; events=[]
    if latest:
        rid=latest["run_id"]
        beds=[dict(r) for r in conn.execute("SELECT bed, COUNT(*) AS samples, MAX(score) AS peak_score, SUM(CASE WHEN band IN ('red','danger','emergency') THEN 1 ELSE 0 END) AS high_risk_samples, MAX(t) AS duration_s FROM scores WHERE run_id=? GROUP BY bed ORDER BY bed",(rid,))]
        events=[dict(r) for r in conn.execute("SELECT bed,t,kind,detail FROM decisions WHERE run_id=? ORDER BY t DESC LIMIT 50",(rid,))]
        for e in events:
            try:e["detail"]=json.loads(e["detail"])
            except Exception:pass
    conn.close()
    return {"runs":runs,"latest":latest,"beds":beds,"events":events}

@app.get("/api/history/{bed}")
def api_history(bed: str):
    import sqlite3
    if not os.path.exists(compare_runs.DB): return {"bed":bed,"readings":[],"scores":[]}
    conn=sqlite3.connect(compare_runs.DB); conn.row_factory=sqlite3.Row
    readings=[dict(r) for r in conn.execute("SELECT run_id,t,sensor,value FROM readings WHERE bed=? ORDER BY run_id DESC,t DESC LIMIT 500",(bed,))]
    scores=[dict(r) for r in conn.execute("SELECT run_id,t,score,band,parts FROM scores WHERE bed=? ORDER BY run_id DESC,t DESC LIMIT 300",(bed,))]
    conn.close(); return {"bed":bed,"readings":readings,"scores":scores}

@app.websocket("/ws/studio")
async def ws_studio(ws: WebSocket):
    await ws.accept()
    studio_clients.add(ws)
    await ws.send_text(json.dumps({"type": "hello", "state": state, "snapshot": snapshot}))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        studio_clients.discard(ws)


@app.websocket("/ws")
async def ws_dashboard(ws: WebSocket):
    await ws.accept()
    dash_clients.add(ws)
    await ws.send_text(json.dumps({"type": "snapshot", "data": snapshot}))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        dash_clients.discard(ws)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"ICU Simulation Studio running at http://{host}:{port}  (Ctrl+C to quit)")
    if host == "127.0.0.1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
