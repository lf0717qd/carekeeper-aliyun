# -*- coding: utf-8 -*-
"""SQLite repository for the demo. Production should use RDS/TableStore."""
from __future__ import annotations
import json, os, sqlite3, tempfile, threading, time

DB_PATH = os.getenv("DB_PATH") or os.path.join(tempfile.gettempdir(), "carekeeper.db")
_LOCK = threading.Lock()


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def init(users: dict, patients: dict) -> None:
    with _LOCK, _conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS users (account TEXT PRIMARY KEY, password TEXT, role TEXT, name TEXT, patient_ids TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS sites (id TEXT PRIMARY KEY, data TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS patients (id TEXT PRIMARY KEY, data TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, patient TEXT, kind TEXT, score INTEGER, comment TEXT, status TEXT, follow_up TEXT, created_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS templates (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, channel TEXT, variant TEXT, text TEXT, sent INTEGER, positive INTEGER, active INTEGER)")
        c.execute("CREATE TABLE IF NOT EXISTS annotations (id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id TEXT, dialect TEXT, assignee TEXT, status TEXT, label TEXT, note TEXT, created_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS releases (id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT, percent INTEGER, status TEXT, note TEXT, created_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS terms (id INTEGER PRIMARY KEY AUTOINCREMENT, term TEXT, standard TEXT, kind TEXT, status TEXT, reviewer TEXT, note TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS hotwords (id INTEGER PRIMARY KEY AUTOINCREMENT, wrong TEXT, right TEXT, active INTEGER, note TEXT)")
        for account, u in users.items():
            c.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,?,?)", (account, u["password"], u["role"], u["name"], json.dumps(u["patient_ids"], ensure_ascii=False)))
        sites = {
            "guangzhou": {"id": "guangzhou", "name": "广州荔湾", "dialect": "粤语", "voice": "zh-HK", "kb_scope": "全科/伤口/跌倒", "alert_target": "家属+医生", "status": "active"},
            "shantou": {"id": "shantou", "name": "汕头金平", "dialect": "潮汕话", "voice": "teochew", "kb_scope": "全科/跌倒", "alert_target": "家属+社区", "status": "l1_only"},
            "hakka": {"id": "hakka", "name": "梅州梅县", "dialect": "客家话", "voice": "hakka", "kb_scope": "全科/跌倒", "alert_target": "家属+社区", "status": "l1_only"},
        }
        for sid, site in sites.items():
            c.execute("INSERT OR REPLACE INTO sites VALUES (?,?)", (sid, json.dumps(site, ensure_ascii=False)))
        for pid, p in patients.items():
            c.execute("INSERT OR REPLACE INTO patients VALUES (?,?)", (pid, json.dumps(p, ensure_ascii=False)))
        if c.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0:
            seed = [
                ("陈婆婆", "csat", 5, "姑娘讲得慢，听得明", "done", "已电话回访", "2026-11-20 09:10"),
                ("李伯", "csat", 3, "血压高那段太快", "open", "", "2026-11-20 10:20"),
                ("陈先生", "followup", 4, "想知复诊带什么", "open", "", "2026-11-20 11:05"),
                ("陈婆婆", "csat", 4, "希望多讲一次用药", "done", "已加提醒", "2026-11-19 16:40"),
            ]
            c.executemany("INSERT INTO feedback (patient,kind,score,comment,status,follow_up,created_at) VALUES (?,?,?,?,?,?,?)", seed)
        if c.execute("SELECT COUNT(*) FROM templates").fetchone()[0] == 0:
            seed = [
                ("血压高-提醒复测", "voice", "A", "婆婆，坐低休息十分钟，再量一次血压。", 120, 38, 1),
                ("血压高-提醒复测", "voice", "B", "婆婆，先坐低唞顺，十分钟后再量，唔好自己加药。", 118, 51, 1),
                ("漏服药-先问药师", "voice", "A", "唔好自己补服，我帮你问药师。", 80, 24, 1),
                ("漏服药-先问药师", "voice", "B", "漏咗一次先唔好补，等药师覆你，安全啲。", 76, 32, 1),
            ]
            c.executemany("INSERT INTO templates (name,channel,variant,text,sent,positive,active) VALUES (?,?,?,?,?,?,?)", seed)
        if c.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 0:
            seed = [
                ("KB-WOUND-001-C012", "粤语", "阿May", "pending", "", "", "2026-11-20 09:00"),
                ("KB-FALL-001-C003", "粤语", "阿May", "review", "跌倒", "边界清楚", "2026-11-20 09:30"),
                ("KB-HYPOG-001-C002", "粤语", "阿Ken", "pending", "", "", "2026-11-20 10:00"),
                ("KB-OST2025-001-C005", "粤语", "阿Ken", "done", "造口", "通过", "2026-11-19 15:20"),
            ]
            c.executemany("INSERT INTO annotations (chunk_id,dialect,assignee,status,label,note,created_at) VALUES (?,?,?,?,?,?,?)", seed)
        if c.execute("SELECT COUNT(*) FROM releases").fetchone()[0] == 0:
            seed = [
                ("v1.1.99", 100, "stable", "当前线上", "2026-11-20 21:45"),
                ("v1.2.00", 10, "canary", "运营后台灰度", "2026-11-20 22:00"),
            ]
            c.executemany("INSERT INTO releases (version,percent,status,note,created_at) VALUES (?,?,?,?,?)", seed)
        if c.execute("SELECT COUNT(*) FROM hotwords").fetchone()[0] == 0:
            seed = [
                ("换骗", "换片", 1, "ASR常见误识"),
                ("换遍", "换片", 1, "ASR常见误识"),
                ("尿骗", "尿片", 1, "ASR常见误识"),
                ("心医", "心翳", 1, "胸闷口语"),
                ("脑退话", "脑退化", 1, "认知口语"),
                ("压苍", "压疮", 1, "伤口术语"),
                ("甜尿病", "糖尿病", 1, "糖尿病口语"),
            ]
            c.executemany("INSERT INTO hotwords (wrong,right,active,note) VALUES (?,?,?,?)", seed)
        if c.execute("SELECT COUNT(*) FROM terms").fetchone()[0] == 0:
            seed = [
                ("换片", "失禁 护理 更换", "term", "pending", "", ""),
                ("甜尿", "糖尿病", "term", "pending", "", ""),
                ("心翳", "胸闷", "term", "pending", "", ""),
                ("脑退化", "认知 记忆 痴呆", "term", "pending", "", ""),
                ("白车", "救护车 急救 120", "term", "pending", "", ""),
                ("银行", "ngan4 hong4", "polyphone", "pending", "", ""),
                ("重量", "cung5 loeng6", "polyphone", "pending", "", ""),
            ]
            c.executemany("INSERT INTO terms (term,standard,kind,status,reviewer,note) VALUES (?,?,?,?,?,?)", seed)
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


def _rows(sql, args=()):
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def _exec(sql, args=()):
    with _LOCK, _conn() as c:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def admin_overview():
    return {
        "feedback": _rows("SELECT * FROM feedback ORDER BY id DESC"),
        "templates": _rows("SELECT * FROM templates ORDER BY name, variant"),
        "annotations": _rows("SELECT * FROM annotations ORDER BY id DESC"),
        "releases": _rows("SELECT * FROM releases ORDER BY id DESC"),
        "terms": _rows("SELECT * FROM terms ORDER BY id"),
        "sites": [json.loads(r["data"]) for r in _rows("SELECT data FROM sites ORDER BY id")],
        "hotwords": _rows("SELECT * FROM hotwords ORDER BY id"),
    }


def update_feedback(fid, status, follow_up):
    _exec("UPDATE feedback SET status=?, follow_up=? WHERE id=?", (status, follow_up, fid))


def save_template(tid, active):
    _exec("UPDATE templates SET active=? WHERE id=?", (1 if active else 0, tid))


def update_annotation(aid, status, label, note):
    _exec("UPDATE annotations SET status=?, label=?, note=? WHERE id=?", (status, label, note, aid))


def add_release(version, percent, note=""):
    _exec("INSERT INTO releases (version,percent,status,note,created_at) VALUES (?,?,?,?,?)", (version, int(percent), "canary", note, time.strftime("%Y-%m-%d %H:%M")))


def set_release(rid, status, percent=None):
    if percent is None:
        _exec("UPDATE releases SET status=? WHERE id=?", (status, rid))
    else:
        _exec("UPDATE releases SET status=?, percent=? WHERE id=?", (status, int(percent), rid))


def review_term(tid, status, note):
    _exec("UPDATE terms SET status=?, note=? WHERE id=?", (status, note, tid))


def get_site(sid: str):
    rows = _rows("SELECT data FROM sites WHERE id=?", (sid,))
    return json.loads(rows[0]["data"]) if rows else None


def update_site(sid: str, data: dict):
    _exec("UPDATE sites SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), sid))


def get_hotwords():
    return _rows("SELECT * FROM hotwords ORDER BY id")


def add_hotword(wrong: str, right: str, note: str = ""):
    _exec("INSERT INTO hotwords (wrong,right,active,note) VALUES (?,?,?,?)", (wrong, right, 1, note))


def toggle_hotword(hid: int, active: bool):
    _exec("UPDATE hotwords SET active=? WHERE id=?", (1 if active else 0, hid))
