"""
SQLite log of everything, so a reactive run and a predictive run can be compared.
One file: sim.db
"""
import json
import os
import sqlite3
import time

from .common import ROOT

DB_PATH = os.path.join(ROOT, "sim.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs      (run_id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT, started REAL, config TEXT);
CREATE TABLE IF NOT EXISTS readings  (run_id INT, bed TEXT, t REAL, sensor TEXT, value TEXT);
CREATE TABLE IF NOT EXISTS scores    (run_id INT, bed TEXT, t REAL, score INT, band TEXT, parts TEXT, severity REAL);
CREATE TABLE IF NOT EXISTS decisions (run_id INT, bed TEXT, t REAL, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS actions   (run_id INT, bed TEXT, t REAL, actuator TEXT, state INT, reason TEXT);
"""


class Database:
    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.run_id = None

    def start_run(self, mode, config):
        cur = self.conn.execute("INSERT INTO runs(mode, started, config) VALUES (?,?,?)",
                                (mode, time.time(), json.dumps(config)))
        self.conn.commit()
        self.run_id = cur.lastrowid
        return self.run_id

    def reading(self, bed, t, sensor, value):
        self.conn.execute("INSERT INTO readings VALUES (?,?,?,?,?)", (self.run_id, bed, t, sensor, str(value)))

    def score(self, bed, t, score, band, parts, severity=None):
        self.conn.execute("INSERT INTO scores VALUES (?,?,?,?,?,?,?)",
                          (self.run_id, bed, t, score, band, json.dumps(parts), severity))

    def decision(self, bed, t, kind, detail):
        self.conn.execute("INSERT INTO decisions VALUES (?,?,?,?,?)", (self.run_id, bed, t, kind, json.dumps(detail)))

    def action(self, bed, t, actuator, on, reason):
        self.conn.execute("INSERT INTO actions VALUES (?,?,?,?,?,?)", (self.run_id, bed, t, actuator, int(on), reason))

    def commit(self):
        self.conn.commit()
