# MediWatch dashboard and publishing guide

This is a copy of the supplied `icu_simulator` project with a separate landing page added. The source ZIP was not modified.

## What changed

- `/` now serves `static/landing.html`, a project overview, feature guide, and quick manual.
- The **Go to the Simulator** buttons open `/simulator`, which serves the existing `static/home.html` ward builder.
- Existing `/studio`, `/dashboard`, `/manual`, APIs, and MQTT simulator logic are retained.
- `HOST` and `PORT` environment variables can be set when running the server on a host. Local defaults remain `127.0.0.1` and `8000`.
- Docker Compose files are included for publishing the web app with a private Mosquitto service and persistent run database.

## Mobile and desktop layout

The new landing page uses responsive CSS breakpoints for tablet and phone widths. The existing ward builder, studio, and Patient Lab also contain responsive CSS layouts. Open the deployed site on a phone or use browser device emulation to check the navigation, bed controls, tables, and forms at your target screen widths before sharing it. The landing page navigation links collapse on narrow screens; the primary **Open Simulator** button remains available.

## Run locally on Windows

1. Install Python 3.10+ and Mosquitto.
2. Open this project folder (`icu_simulator`) in PowerShell.
3. Create and install the environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

4. Start Mosquitto in a separate terminal if it is not running as a service:

   ```powershell
   & "C:\Program Files\mosquitto\mosquitto.exe" -v
   ```

5. Start the app:

   ```powershell
   .\.venv\Scripts\python.exe server.py
   ```

6. Visit `http://127.0.0.1:8000/`. Select **Go to the Simulator** to open the existing ward builder at `/simulator`.

## Publish it as a website with Docker Compose

The project includes `Dockerfile`, `docker-compose.yml`, and `deploy/mosquitto.conf` for a small VPS or VM with Docker Compose. This runs the Python app and Mosquitto together; the MQTT broker port is not published to the internet. The ward configuration and SQLite run history are persisted.

1. Copy the `MediWatch_Dashboard_Project` folder to a VPS/VM that has Docker Engine and the Docker Compose plugin, or push the folder to a private Git repository and clone it there.
2. In the project folder, start the services:

   ```sh
   docker compose up --build -d
   ```

3. Point your domain's DNS A record to the server IP.
4. Install Caddy on the Ubuntu host, configure it with your domain, an authentication password hash, and `reverse_proxy 127.0.0.1:8000`. Caddy can obtain HTTPS certificates automatically. The Compose file binds the app only to localhost; do not change this to a public binding.
5. Configure the host/provider firewall to allow inbound SSH (22), HTTP (80), and HTTPS (443). Do not open 8000, 1883, or 2375 publicly.
6. Start the services. Open `https://your-domain/`, enter the username and password configured in Caddy, then use **Go to the Simulator**. The app uses the internal `mqtt` service name; no local Mosquitto install is needed on the server.
7. Keep the project config and Docker volumes backed up. The ward config is mounted from `config/ward_config.json`; simulation history is stored in the `mediwatch_db` Docker volume.

To stop the app without deleting saved data, run `docker compose down`. Do not add `--volumes` if you want to keep the saved database and broker state.

### Public access

The supplied app has no built-in login or user authorization. The Caddy `basic_auth` reverse-proxy option can require a login for the whole site. Use a unique strong password, and use HTTPS; basic authentication over plain HTTP is not secure. Controls can start runs, change configuration, inject readings, and trigger simulated events. Use synthetic demonstration data only.

## Alternative: run without Docker

This is a Python + WebSocket + MQTT application, not a static HTML-only website. A static hosting service cannot run the simulator by itself. Deploy the `icu_simulator` folder to a Python host, VM, or container that can run the FastAPI process and a Mosquitto broker. Keep the broker reachable from the app host and retain writable persistent storage for `config/ward_config.json` and the SQLite run database (`sim.db`). Configure `config/ward_config.json`'s MQTT host/port for the broker address on your host (it currently uses `localhost:1883`).

Set these environment variables in the hosting service:

```text
HOST=0.0.0.0
PORT=<port supplied by the hosting service>
```

Set the service start command to:

```text
python server.py
```

Then attach a domain and HTTPS using the host's reverse proxy or managed TLS. Verify that WebSocket connections are supported, since live updates use `/ws`. If the broker runs in another container, change the MQTT host in the ward config to that broker's service name rather than `localhost`.

## Main code changes

In `server.py`, the root route now serves the new landing page, and `/simulator` serves the existing ward builder:

```python
@app.get("/")
def landing_page():
    return FileResponse(os.path.join(ROOT, "static", "landing.html"))


@app.get("/simulator")
def simulator_page():
    return FileResponse(os.path.join(ROOT, "static", "home.html"))
```

`static/landing.html` contains the page sections and links into the existing simulator. The bottom of `server.py` reads `HOST` and `PORT` for hosting while preserving local defaults.

