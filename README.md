# ICU Simulation Studio

A Wokwi-style simulator for an IoT early-warning system on a hospital ward.
Python simulates the patients, sensors and actuators. Every reading and
command travels through a real Mosquitto MQTT broker. A central engine
scores NEWS2, runs the rule engine and the look-ahead. SQLite logs every
run. FastAPI + WebSockets drive the live canvas in your browser.

## Install (once)
1. Python 3.10+ (tick "Add python.exe to PATH" on Windows)
2. `python -m pip install -r requirements.txt`
3. Mosquitto: https://mosquitto.org/download/  (Windows x64 installer)

## Run
1. Make sure Mosquitto is running
   (Windows: `"C:\Program Files\mosquitto\mosquitto.exe" -v` in its own window,
   or it is already running as a service).
2. In the project folder:  `python server.py`
3. The studio opens at http://127.0.0.1:8000

In the studio:
* drag sensors and actuators from the left onto a bed; click any part to set
  interval, noise and dropout (saved to config/ward_config.json)
* choose Reactive or Predictive and press **Start simulation**
* wires light up as MQTT messages flow; the MQTT monitor shows every message
* during a run: click a sensor and untick "Probe attached", or press
  "Simulate collapse" on a bed
* Results tab, Run comparison: runs both modes through Mosquitto and reads sim.db

Other entry points
* `python run_all.py --mode predictive --headless`  (no browser)
* `python compare_runs.py`                          (results table in the terminal)
* `python setup_window.py`                          (Tkinter setup window)
* http://127.0.0.1:8000/dashboard                   (simple ward dashboard)

## Files (block diagram numbers)
| File | Block |
|---|---|
| config/*.json | settings, scenarios, rule thresholds |
| simulator/patient.py | 1 Virtual patients, 7 Patient responds |
| simulator/sensors.py | 2 Monitoring devices |
| simulator/ward.py | patients + sensors + actuators as MQTT clients |
| simulator/engine.py | 3 Central system, 5a rule engine |
| simulator/news2.py | 4 Warning score |
| simulator/predictor.py | 5b Look ahead |
| simulator/actuators.py | 6a / 6b actuators |
| simulator/database.py | SQLite log |
| server.py | FastAPI + WebSockets + MQTT bridge, starts and stops the run |
| static/studio.html | the Wokwi-style studio |
| static/dashboard.html | simple dashboard |

## MQTT topics
    ward/<bed>/vitals/<sensor>  {"t": 12, "value": 88}                 ward -> engine
    ward/<bed>/cmd              {"actuator": "oxygen", "on": true}     engine -> ward
    ward/<bed>/sensor_cfg       {"interval_s": 1} | {"reset": true} | {"sensor": "spo2", "connected": false}
    ward/<bed>/inject           {"collapse": true}                     studio -> ward
    ward/<bed>/actuators        {"oxygen": true, ...}                  ward -> everyone
    ward/<bed>/status           score, band, vitals, prediction        engine -> studio
    ward/<bed>/event            timeline entries
    ward/<bed>/truth            hidden severity (logging only)
    ward/clock, ward/control

Watch raw traffic:  `mosquitto_sub -t "ward/#" -v`
(Windows: `"C:\Program Files\mosquitto\mosquitto_sub.exe" -t "ward/#" -v`)


## Manual Patient Lab (added)
Start Mosquitto and `python server.py`, start a ward simulation in the ICU Studio, then open `http://127.0.0.1:8000/manual`. Select a configured bed and apply custom HR, SpO2, RR, systolic BP and temperature readings. Readings are published to the live MQTT vital topics. The automatic ward publisher may overwrite manual values on later cycles. This is a simulator-only test feature and not a medical device.


## Updated patient-first interface
The root URL now opens the redesigned dashboard in `static/home.html`; the original technical studio is at `/studio`. See `START_HERE.md` for setup and limitations.

## Final review fixes (November 2026)

- **Stop & save:** Stop now sends a graceful stop request to the virtual ward. The ward publishes its final stop marker, the monitoring engine commits the readings, scores, alerts and actions collected so far to `sim.db`, and the server then releases the run processes. A new run can be started afterwards.
- **Comparison:** The Run & monitor comparison now runs the same configured ward in Reactive and Predictive modes, waits for completion, and displays a side-by-side comparison table. The Studio Results tab also reports comparison failures instead of silently doing nothing.
- **Scenario library:** `/api/scenarios` now exposes both the scenario-name list (for the Studio editor) and the full scenario profiles (for the Ward Builder). This fixes the previous list/object mismatch that caused scenario values to appear as `undefined` and prevented valid scenario selection.
- **Readable alerts:** The Ward Builder now shows a prominent, dismissible patient alert when the monitoring engine publishes an event, with the bed and event explanation. Critical/urgent events are visually distinguished.
- **Run controls:** The Ward Builder includes a dedicated **Stop & save** button and disables conflicting setup actions while a run is active or stopping.

The simulator remains an educational software simulation. Its generated scores and simulated actuator actions are not clinical diagnoses or real treatment.
