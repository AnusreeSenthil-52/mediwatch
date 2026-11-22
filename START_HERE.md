# MEDIWATCH — Updated Complete Project

## Run on Windows / VS Code
1. Extract the ZIP and open the `icu_simulator` folder (the folder containing `server.py` and `requirements.txt`).
2. Create environment: `py -m venv .venv`
3. Install packages: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
4. Start Mosquitto in a separate terminal if it is not already running:
   `& "C:\Program Files\mosquitto\mosquitto.exe" -v`
5. Start the web app:
   `.\.venv\Scripts\python.exe server.py`
6. Open `http://127.0.0.1:8000`.

## Pages
- `/` — redesigned patient-first ward overview, manual inputs, scenario controls.
- `/manual` — Patient Lab form.
- `/dashboard` — existing analytics dashboard.
- `/studio` — original technical studio/canvas.

## What changed in this package
- The root route now opens a new patient-first dashboard (`static/home.html`) instead of the old canvas-style studio. This is a visible interface change.
- The original studio remains available at `/studio`.
- The new home page shows patient cards, vital values, simple status indicators, mode selection, start/stop controls, manual readings, configured scenario selection, collapse trigger, MQTT status and recent local events.
- Added `/api/state` to expose current server state for the UI.
- Retained `/manual` and `/api/manual-readings` from the previous update.
- Added validation of Python syntax during packaging.

## Important limits and safety
- Manual readings are published to the MQTT vital topics. Automatic sensor simulation can overwrite them in later cycles; a persistent override mode is not implemented.
- Scenario selection writes to configuration and is best changed while the simulation is stopped. The scenario names describe simplified synthetic behaviours, not validated medical disease models.
- The current predictor remains trend-based look-ahead; this package does not claim a trained, clinically validated ML model. Do not report ML accuracy unless you train and evaluate a model on an appropriate documented dataset.
- Alerts and actuators are simulated software events, not real nurse calls or treatment.
- Test locally before demonstrating. MQTT message schema and live UI updates can vary with the original code version.


## Updated interface
The main URL `/` now opens the dark three-panel Ward Builder inspired by the provided reference: component palette, selectable patient beds, generated configuration, patient/scenario controls, manual vital readings, MQTT status, and simulation controls. `/studio` keeps the previous technical studio, `/dashboard` the monitoring dashboard, and `/manual` the manual lab. The builder edits the ward configuration in the browser; use Validate and then Save & start simulation to save changes and launch. Disease-labelled scenarios remain simplified simulation profiles, not clinically validated models.


## Functional Ward Builder update
- Main tabs now switch to Rules, Scenarios, and Run & Monitor/Analytics views.
- Run summaries, per-bed NEWS2 summaries, decisions, and previous runs are read from `sim.db`.
- Manual vital values are held as overrides for that bed for the current simulation, rather than being replaced immediately by synthetic sensor values.
- Patient bed cards show live vital values and change to amber/red borders for warning/high-risk thresholds.
- The existing predictor is a rule/model-based look-ahead simulation, not a clinically validated or trained ML model.

- Added an educational logistic-regression risk classifier trained on generated synthetic vital-sign examples. Its probability is a software demonstration, not a clinical prediction; no real clinical dataset or clinical validation is included.

- Fall/accelerometer and bed-occupancy sensors now produce simulated readings if added to a bed. Network components are configuration placeholders, not a physical ESP32 connection.


## Sensor fault simulation (new)
1. Start Mosquitto and the MEDIWATCH server, then open `http://127.0.0.1:8000`.
2. Save the ward configuration and start a simulation.
3. Open the **Sensor faults** tab.
4. Choose a configured bed and sensor, select one of the five fault types, set a duration in simulated seconds, and click **Apply fault**.
5. Use **Restore selected sensor** to clear a fault manually. A timed fault also clears when its simulated duration expires.

Supported fault tests:
- **Sensor disconnected:** stops readings; stale detection uses `stale_reading_s` (15 simulated seconds by default).
- **Frozen reading:** repeats the same value; five identical samples are used as the injected-fault detection criterion.
- **Noisy reading:** increases measurement noise and applies a rolling median filter to the last five samples for monitoring calculations.
- **Communication dropout:** simulates loss of sensor messages; it is separate from physical probe disconnection.
- **Invalid reading:** sends out-of-range values, which are rejected by the monitoring engine.

When a configured sensor is unavailable or invalid, MEDIWATCH marks monitoring incomplete and pauses NEWS2/ML/predictive calculations for that bed until the sensor is restored and a fresh valid reading is received. Sensor-fault events are also written to the run decision history. These are software fault-injection tests; they do not test real hardware or a real network failure.
