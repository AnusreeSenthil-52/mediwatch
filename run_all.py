"""
Command-line launcher (the studio is the easier way: python server.py).
Starts engine + ward, and the server unless --headless. Mosquitto must be running.

    python run_all.py                       # uses config/ward_config.json
    python run_all.py --mode reactive       # override the mode
    python run_all.py --headless            # no dashboard, exit when the run ends
"""
import argparse
import subprocess
import sys
import time

PY = sys.executable


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="ward_config.json")
    ap.add_argument("--mode", choices=["reactive", "predictive"])
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    procs = []
    engine_cmd = [PY, "-m", "simulator.engine", "--config", args.config]
    if args.mode:
        engine_cmd += ["--mode", args.mode]
    procs.append(subprocess.Popen(engine_cmd))
    if not args.headless:
        procs.append(subprocess.Popen([PY, "server.py"]))      # the server opens the browser itself
        time.sleep(2)
    time.sleep(1)                                   # let subscribers connect first
    ward = subprocess.Popen([PY, "-m", "simulator.ward", "--config", args.config])
    try:
        ward.wait()
        procs[0].wait(timeout=10)                   # engine saves and exits
        if not args.headless:
            print("Run finished. Dashboard still open - press Ctrl+C to quit.")
            procs[-1].wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs + [ward]:
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()
