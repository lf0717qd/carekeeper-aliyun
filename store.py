# -*- coding: utf-8 -*-
"""SQLite repository for the demo. Production should use RDS/TableStore."""
from __future__ import annotations
import json, os, sqlite3, tempfile, threading

DB_PATH = os.getenv("DB_PATH") or os.path.join(tempfile.gettempdir(), "carekeeper.db")
_LOCK = threading.Lock()


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def init(users: dict, patients: dict) -> None:
    with _LOCK, _conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS users (account TEXT PRIMARY KEY, password TEXT, role TEXT, name TEXT, patient_ids TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS patients (id TEXT PRIMARY KEY, data TEXT)")
        for account, u in users.items():
            c.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,?,?)", (account, u["password"], u["role"], u["name"], json.dumps(u["patient_ids"], ensure_ascii=False)))
        for pid, p in patients.items():
            c.execute("INSERT OR REPLACE INTO patients VALUES (?,?)", (pid, json.dumps(p, ensure_ascii=False)))
        c.commit()


def get_user(account: str):
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE account=?", (account,)).fetchone()
    if not row:
        return None
    return {"password": row["password"], "role": row["role"], "name": row["name"], "patient_ids": json.loads(row["patient_ids"])}


def get_patients(ids):
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    with _conn() as c:
        rows = c.execute("SELECT data FROM patients WHERE id IN (" + marks + ")", tuple(ids)).fetchall()
    by_id = {json.loads(r["data"])["id"]: json.loads(r["data"]) for r in rows}
    return [by_id[x] for x in ids if x in by_id]
