# -*- coding: utf-8 -*-
"""SQLite repository for the demo. Production should use RDS/TableStore."""
from __future__ import annotations
import json, os, sqlite3, tempfile, threading, time
from datetime import datetime
from zoneinfo import ZoneInfo

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
        c.execute("CREATE TABLE IF NOT EXISTS handoffs (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, session_id TEXT, reason TEXT, status TEXT, owner TEXT, created_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS features (name TEXT PRIMARY KEY, enabled INTEGER, note TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS bp_records (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, measured_at TEXT, systolic INTEGER, diastolic INTEGER, source TEXT, note TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS medications (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, name TEXT, dose TEXT, instruction TEXT, slot TEXT, active INTEGER)")
        c.execute("CREATE TABLE IF NOT EXISTS med_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, med_id INTEGER, slot TEXT, status TEXT, logged_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS followups (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, appointment_at TEXT, hospital TEXT, department TEXT, remind_at TEXT, status TEXT, notes TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS doctor_patient (patient_id TEXT PRIMARY KEY, doctor_account TEXT, bound_at TEXT, bound_by TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS patient_profiles (patient_id TEXT PRIMARY KEY, folder TEXT, diagnosis TEXT, allergies TEXT, note TEXT, updated_by TEXT, updated_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS daily_observations (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, observed_date TEXT, heart_rate INTEGER, systolic INTEGER, diastolic INTEGER, respiratory_rate INTEGER, sputum TEXT, urine TEXT, note TEXT, recorded_by TEXT, recorded_at TEXT, UNIQUE(patient_id, observed_date))")
        c.execute("CREATE TABLE IF NOT EXISTS med_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, drug TEXT, dose TEXT, frequency TEXT, duration TEXT, note TEXT, doctor TEXT, created_at TEXT, active INTEGER)")
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
        if c.execute("SELECT COUNT(*) FROM bp_records").fetchone()[0] == 0:
            seed = [
                ("chen", "2026-11-21 08:40", 148, 86, "manual", "早上"),
                ("chen", "2026-11-20 20:10", 142, 84, "manual", "晚上"),
                ("chen", "2026-11-20 08:30", 150, 88, "device", "血压计"),
                ("chen", "2026-11-19 08:20", 138, 82, "manual", "早上"),
            ]
            c.executemany("INSERT INTO bp_records (patient_id,measured_at,systolic,diastolic,source,note) VALUES (?,?,?,?,?,?)", seed)
        if c.execute("SELECT COUNT(*) FROM medications").fetchone()[0] == 0:
            seed = [
                ("chen", "氨氯地平", "5mg", "早上饭后一粒", "am", 1),
                ("chen", "二甲双胍", "0.5g", "早晚饭后各一粒", "both", 1),
            ]
            c.executemany("INSERT INTO medications (patient_id,name,dose,instruction,slot,active) VALUES (?,?,?,?,?,?)", seed)
        if c.execute("SELECT COUNT(*) FROM med_logs").fetchone()[0] == 0:
            c.execute("INSERT INTO med_logs (patient_id,med_id,slot,status,logged_at) VALUES (?,?,?,?,?)", ("chen", 1, "am", "done", "2026-11-21 08:50"))
        if c.execute("SELECT COUNT(*) FROM followups").fetchone()[0] == 0:
            c.execute("INSERT INTO followups (patient_id,appointment_at,hospital,department,remind_at,status,notes) VALUES (?,?,?,?,?,?,?)", ("chen", "2026-11-25 09:00", "社区医院", "二楼慢病门诊", "2026-11-24 09:00", "upcoming", "带血压记录"))
        if c.execute("SELECT COUNT(*) FROM doctor_patient").fetchone()[0] == 0:
            for pid in ("chen", "li"):
                c.execute("INSERT OR IGNORE INTO doctor_patient (patient_id,doctor_account,bound_at,bound_by) VALUES (?,?,?,?)", (pid, "13800000003", "2026-11-21 09:00", "admin"))
        if c.execute("SELECT COUNT(*) FROM patient_profiles").fetchone()[0] == 0:
            c.execute("INSERT OR REPLACE INTO patient_profiles (patient_id,folder,diagnosis,allergies,note,updated_by,updated_at) VALUES (?,?,?,?,?,?,?)", ("chen", "高血压", "高血压、2型糖尿病", "", "独居；儿子陈先生为紧急联系人", "13800000003", "2026-11-21 09:05"))
            c.execute("INSERT OR REPLACE INTO patient_profiles (patient_id,folder,diagnosis,allergies,note,updated_by,updated_at) VALUES (?,?,?,?,?,?,?)", ("li", "慢阻肺", "高血压、慢阻肺", "", "独居；女儿李小姐", "13800000003", "2026-11-21 09:06"))
        if c.execute("SELECT COUNT(*) FROM daily_observations").fetchone()[0] == 0:
            seed = [
                ("chen", "2026-11-19", 78, 138, 82, 18, "无", "正常", "晨间护理", "13800000003", "2026-11-19 08:10"),
                ("chen", "2026-11-20", 82, 142, 84, 19, "有", "正常", "晨间护理", "13800000003", "2026-11-20 08:20"),
                ("chen", "2026-11-21", 84, 148, 86, 20, "有", "减少", "晨间护理；已嘱复测血压", "13800000003", "2026-11-21 08:30"),
                ("li", "2026-11-21", 92, 132, 78, 22, "有", "正常", "晨间护理", "13800000003", "2026-11-21 08:40"),
            ]
            c.executemany("INSERT INTO daily_observations (patient_id,observed_date,heart_rate,systolic,diastolic,respiratory_rate,sputum,urine,note,recorded_by,recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", seed)
        if c.execute("SELECT COUNT(*) FROM med_plans").fetchone()[0] == 0:
            c.execute("INSERT INTO med_plans (patient_id,drug,dose,frequency,duration,note,doctor,created_at,active) VALUES (?,?,?,?,?,?,?,?,?)", ("chen", "氨氯地平", "5mg", "每日1次（早上）", "长期", "比赛演示；按医嘱", "13800000003", "2026-11-21 09:10", 1))
        if c.execute("SELECT COUNT(*) FROM features").fetchone()[0] == 0:
            seed = [("agent_enabled", 1, "Agent turn"), ("llm_enabled", 1, "LLM 回答"), ("kb_enabled", 1, "KB 检索"), ("tts_enabled", 1, "语音播报"), ("maintenance", 0, "维护模式")]
            c.executemany("INSERT INTO features (name,enabled,note) VALUES (?,?,?)", seed)
        if c.execute("SELECT COUNT(*) FROM handoffs").fetchone()[0] == 0:
            c.execute("INSERT INTO handoffs (patient_id,session_id,reason,status,owner,created_at) VALUES (?,?,?,?,?,?)", ("chen", "demo:chen", "2次听唔明", "open", "", "2026-11-21 12:00"))
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
        "handoffs": _handoffs_with_sla(),
        "features": _rows("SELECT * FROM features ORDER BY name"),
        "bp_records": _rows("SELECT * FROM bp_records ORDER BY measured_at DESC LIMIT 30"),
        "medications": _rows("SELECT * FROM medications ORDER BY id"),
        "followups": _rows("SELECT * FROM followups ORDER BY appointment_at"),
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


def add_handoff(patient_id: str, session_id: str, reason: str):
    _exec("INSERT INTO handoffs (patient_id,session_id,reason,status,owner,created_at) VALUES (?,?,?,?,?,?)",
          (patient_id, session_id, reason, "open", "", time.strftime("%Y-%m-%d %H:%M")))


def update_handoff(hid: int, status: str, owner: str = ""):
    _exec("UPDATE handoffs SET status=?, owner=? WHERE id=?", (status, owner, hid))


def get_features():
    return _rows("SELECT * FROM features ORDER BY name")


def set_feature(name: str, enabled: bool):
    _exec("UPDATE features SET enabled=? WHERE name=?", (1 if enabled else 0, name))


def _handoffs_with_sla():
    rows = _rows("SELECT * FROM handoffs ORDER BY id DESC")
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    for r in rows:
        try:
            created = datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M")
            age = int((now - created).total_seconds() // 60)
        except Exception:
            age = 0
        r["age_minutes"] = age
        if r["status"] == "done":
            r["sla"] = "done"
        elif age >= (15 if r["status"] == "open" else 30):
            r["sla"] = "overdue"
        else:
            r["sla"] = "ok"
    return rows


def add_bp(patient_id: str, measured_at: str, systolic: int, diastolic: int, source: str, note: str = ""):
    _exec("INSERT INTO bp_records (patient_id,measured_at,systolic,diastolic,source,note) VALUES (?,?,?,?,?,?)", (patient_id, measured_at, systolic, diastolic, source, note))


def add_followup(patient_id: str, appointment_at: str, hospital: str, department: str, remind_at: str, notes: str = ""):
    _exec("INSERT INTO followups (patient_id,appointment_at,hospital,department,remind_at,status,notes) VALUES (?,?,?,?,?,?,?)", (patient_id, appointment_at, hospital, department, remind_at, "upcoming", notes))


def checkin_med(patient_id: str, med_id: int, slot: str):
    _exec("INSERT INTO med_logs (patient_id,med_id,slot,status,logged_at) VALUES (?,?,?,?,?)", (patient_id, med_id, slot, "done", time.strftime("%Y-%m-%d %H:%M")))


def care_data(patient_id: str):
    bps = _rows("SELECT * FROM bp_records WHERE patient_id=? ORDER BY measured_at DESC LIMIT 30", (patient_id,))
    meds = _rows("SELECT * FROM medications WHERE patient_id=? AND active=1 ORDER BY id", (patient_id,))
    logs = _rows("SELECT * FROM med_logs WHERE patient_id=? ORDER BY logged_at DESC LIMIT 30", (patient_id,))
    fus = _rows("SELECT * FROM followups WHERE patient_id=? ORDER BY appointment_at", (patient_id,))
    done = len([x for x in logs if x["status"] == "done"])
    return {"bp": bps, "medications": meds, "med_logs": logs, "followups": fus, "adherence": {"done": done, "total": max(1, len(meds) * 2)},
            "observations": list_observations(patient_id, 14), "profile": get_profile(patient_id), "med_plans": list_med_plans(patient_id)}


def create_user(account: str, password: str, role: str, name: str, patient_ids=None, created_by="admin"):
    if role not in ("elder", "family", "doctor", "admin"):
        raise ValueError("bad role")
    if not account or not password or not name:
        raise ValueError("account/password/name required")
    with _LOCK, _conn() as c:
        if c.execute("SELECT 1 FROM users WHERE account=?", (account,)).fetchone():
            raise ValueError("account exists")
        c.execute("INSERT INTO users (account,password,role,name,patient_ids) VALUES (?,?,?,?,?)", (account, password, role, name, json.dumps(patient_ids or [], ensure_ascii=False)))
        c.commit()


def list_users(role=None):
    sql = "SELECT account,role,name,patient_ids FROM users"
    args = ()
    if role:
        sql += " WHERE role=?"; args = (role,)
    sql += " ORDER BY role,account"
    return [{"account": r["account"], "role": r["role"], "name": r["name"], "patient_ids": json.loads(r["patient_ids"] or "[]")} for r in _rows(sql, args)]


def doctor_has_patient(doctor_account: str, patient_id: str) -> bool:
    row = _rows("SELECT 1 FROM doctor_patient WHERE doctor_account=? AND patient_id=?", (doctor_account, patient_id))
    return bool(row)


def bind_patient(doctor_account: str, patient_id: str, bound_by="admin"):
    with _LOCK, _conn() as c:
        if not c.execute("SELECT 1 FROM patients WHERE id=?", (patient_id,)).fetchone():
            raise ValueError("patient not found")
        row = c.execute("SELECT doctor_account FROM doctor_patient WHERE patient_id=?", (patient_id,)).fetchone()
        if row and row["doctor_account"] != doctor_account:
            raise ValueError("already_bound")
        c.execute("INSERT OR REPLACE INTO doctor_patient (patient_id,doctor_account,bound_at,bound_by) VALUES (?,?,?,?)", (patient_id, doctor_account, time.strftime("%Y-%m-%d %H:%M"), bound_by))
        user = c.execute("SELECT patient_ids FROM users WHERE account=?", (doctor_account,)).fetchone()
        ids = json.loads(user["patient_ids"] or "[]") if user else []
        if patient_id not in ids:
            ids.append(patient_id)
        if user:
            c.execute("UPDATE users SET patient_ids=? WHERE account=?", (json.dumps(ids, ensure_ascii=False), doctor_account))
        c.commit()


def doctor_patients(doctor_account: str):
    rows = _rows("SELECT patient_id FROM doctor_patient WHERE doctor_account=? ORDER BY bound_at", (doctor_account,))
    out = []
    for r in rows:
        pid = r["patient_id"]
        p = _rows("SELECT data FROM patients WHERE id=?", (pid,))
        if not p:
            continue
        data = json.loads(p[0]["data"])
        obs = list_observations(pid, 1)
        out.append({"patient": data, "profile": get_profile(pid), "latest": obs[0] if obs else None})
    return out


def get_profile(patient_id: str):
    rows = _rows("SELECT * FROM patient_profiles WHERE patient_id=?", (patient_id,))
    return rows[0] if rows else {}


def save_profile(patient_id: str, folder: str, diagnosis: str, allergies: str, note: str, updated_by: str):
    _exec("INSERT OR REPLACE INTO patient_profiles (patient_id,folder,diagnosis,allergies,note,updated_by,updated_at) VALUES (?,?,?,?,?,?,?)",
          (patient_id, folder[:40], diagnosis[:120], allergies[:120], note[:200], updated_by, time.strftime("%Y-%m-%d %H:%M")))
    return get_profile(patient_id)


def list_observations(patient_id: str, days: int = 14):
    return _rows("SELECT * FROM daily_observations WHERE patient_id=? ORDER BY observed_date DESC LIMIT ?", (patient_id, max(1, int(days))))


def save_observation(patient_id: str, observed_date: str, heart_rate, systolic, diastolic, respiratory_rate, sputum: str, urine: str, note: str, recorded_by: str):
    _exec("INSERT INTO daily_observations (patient_id,observed_date,heart_rate,systolic,diastolic,respiratory_rate,sputum,urine,note,recorded_by,recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
          "ON CONFLICT(patient_id,observed_date) DO UPDATE SET heart_rate=excluded.heart_rate,systolic=excluded.systolic,diastolic=excluded.diastolic,respiratory_rate=excluded.respiratory_rate,sputum=excluded.sputum,urine=excluded.urine,note=excluded.note,recorded_by=excluded.recorded_by,recorded_at=excluded.recorded_at",
          (patient_id, observed_date[:10], heart_rate, systolic, diastolic, respiratory_rate, sputum[:20], urine[:20], note[:200], recorded_by, time.strftime("%Y-%m-%d %H:%M")))
    return list_observations(patient_id, 1)[0]


def list_med_plans(patient_id: str):
    return _rows("SELECT * FROM med_plans WHERE patient_id=? ORDER BY created_at DESC", (patient_id,))


def add_med_plan(patient_id: str, drug: str, dose: str, frequency: str, duration: str, note: str, doctor: str):
    _exec("INSERT INTO med_plans (patient_id,drug,dose,frequency,duration,note,doctor,created_at,active) VALUES (?,?,?,?,?,?,?,?,?)",
          (patient_id, drug[:60], dose[:40], frequency[:60], duration[:40], note[:160], doctor, time.strftime("%Y-%m-%d %H:%M"), 1))
    return list_med_plans(patient_id)
