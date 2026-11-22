"""
Compare runs stored in sim.db (reactive vs predictive).

    python compare_runs.py              # the last two runs
    python compare_runs.py 3 4          # specific run ids
"""
import os
import sqlite3
import sys

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim.db")


def summary(conn, run_id):
    mode = conn.execute("SELECT mode FROM runs WHERE run_id=?", (run_id,)).fetchone()[0]
    rows = []
    for (bed,) in conn.execute("SELECT DISTINCT bed FROM scores WHERE run_id=? ORDER BY bed", (run_id,)):
        peak, secs_red, secs_orange = conn.execute(
            "SELECT MAX(score), SUM(score>=7), SUM(score>=5 AND score<7) FROM scores WHERE run_id=? AND bed=?",
            (run_id, bed)).fetchone()
        first = lambda kind: conn.execute(
            "SELECT MIN(t) FROM decisions WHERE run_id=? AND bed=? AND kind=?", (run_id, bed, kind)).fetchone()[0]
        emergencies = conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE run_id=? AND bed=? AND kind='emergency'", (run_id, bed)).fetchone()[0]
        rows.append((bed, peak, secs_red or 0, secs_orange or 0, emergencies, first("early"), first("emergency")))
    return mode, rows


def main():
    conn = sqlite3.connect(DB)
    ids = [int(x) for x in sys.argv[1:]] or \
        [r[0] for r in conn.execute("SELECT run_id FROM runs ORDER BY run_id DESC LIMIT 2")][::-1]
    header = f"{'bed':<6}{'peak':>6}{'s in red(>=7)':>15}{'s in orange(5-6)':>18}{'emergencies':>13}{'early at':>10}{'emergency at':>14}"
    for run_id in ids:
        mode, rows = summary(conn, run_id)
        print(f"\nRun {run_id} - {mode.upper()}")
        print(header)
        for bed, peak, red, orange, em, early, emt in rows:
            print(f"{bed:<6}{peak:>6}{red:>15}{orange:>18}{em:>13}{str(early or '-'):>10}{str(emt or '-'):>14}")
        tot_red = sum(r[2] for r in rows)
        print(f"{'total':<6}{'':>6}{tot_red:>15}{sum(r[3] for r in rows):>18}{sum(r[4] for r in rows):>13}")


if __name__ == "__main__":
    main()
