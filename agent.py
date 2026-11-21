# -*- coding: utf-8 -*-
"""Structured agent turn planner: intent, slots, clarification, fallback, handoff."""
from __future__ import annotations
import re

EMERGENCY = re.compile(r"(胸痛|心口痛|唞唔到气|呼吸困难|晕低|晕倒|昏|中风|半边|讲话唔清|大出血|血止唔住|跌倒|撞到头)")
INTENTS = [
    ("emergency", EMERGENCY),
    ("bp", re.compile(r"(血压|血压高|血压低|上压|下压|mmHg)")),
    ("glucose", re.compile(r"(血糖|甜尿|低血糖|高血糖|mmol)")),
    ("medication", re.compile(r"(食药|吃药|用药|漏服|降压药|二甲双胍|氨氯地平|药)")),
    ("wound", re.compile(r"(伤口|压疮|换片|尿片|失禁|造口|敷料)")),
    ("fall", re.compile(r"(跌倒|起身|落床|头晕|行唔稳|扶住)")),
    ("diet", re.compile(r"(食乜|饮食|糖尿餐|盐|糖|饮水)")),
    ("appointment", re.compile(r"(预约|约个|约下|挂号|复诊|覆诊|睇医生|去医院|哪天|几时)")),
    ("report", re.compile(r"(报告|回执|总结|记录|发给家人)")),
    ("staff", re.compile(r"(叫医生|叫家人|转人工|人工|姑娘|医生)")),
    ("greeting", re.compile(r"^(你好|早晨|早安|婆婆|我系|hello|hi)")),
]

REQUIRED = {"bp": ["systolic", "diastolic"], "glucose": ["glucose"], "medication": ["medication"], "appointment": ["appointment_time"]}
PROMPTS = {
    "bp": "你有冇量到血压？上压／下压系几多？",
    "glucose": "血糖机显示几多？系空腹定食后？",
    "medication": "你讲嘅系边只药？早上定晚上？",
    "appointment": "你想约边日？去边间医院／社区？",
}


def classify(text: str):
    for name, pat in INTENTS:
        if pat.search(text):
            return name
    return "unknown"


def extract_slots(text: str):
    slots = {}
    m = re.search(r"(\d{2,3})\s*[/／]\s*(\d{2,3})", text)
    if m:
        slots["systolic"] = int(m.group(1)); slots["diastolic"] = int(m.group(2))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mmol(?:/L)?|血糖)", text, re.I)
    if m:
        slots["glucose"] = float(m.group(1))
    m = re.search(r"(氨氯地平|二甲双胍|降压药|降糖药|药)", text)
    if m:
        slots["medication"] = m.group(1)
    m = re.search(r"(早上|朝早|中午|下午|晚上|今晚|睡前)", text)
    if m:
        slots["time_of_day"] = m.group(1)
    m = re.search(r"(下周三|下星期一|下星期二|下星期四|下星期五|明天|后天|\d{1,2}月\d{1,2}日|\d{1,2}号)", text)
    if m:
        slots["appointment_time"] = m.group(1)
    m = re.search(r"(\d+)\s*(日|天|小时|个钟)", text)
    if m:
        slots["duration"] = m.group(0)
    return slots


def _missing(intent, slots):
    return [k for k in REQUIRED.get(intent, []) if not slots.get(k)]


def plan(text: str, state=None):
    state = dict(state or {})
    slots = dict(state.get("slots") or {})
    slots.update(extract_slots(text))
    failures = int(state.get("failures", 0))
    turns = int(state.get("turns", 0)) + 1
    intent = classify(text)
    if intent == "unknown" and state.get("intent") in REQUIRED and extract_slots(text):
        intent = state["intent"]
    trace = [{"step": "observe", "text": text[:80]}, {"step": "understand", "intent": intent, "slots": slots}]

    if intent == "emergency":
        state.update({"intent": intent, "slots": slots, "failures": 0, "turns": turns})
        return {"intent": "emergency", "action": "emergency", "risk": "high", "needs_human": True,
                "reply": "婆婆，呢啲可能系急症，唔好等。即刻坐低／唔好行，叫家人，必要时打 120。",
                "slots": slots, "state": state, "trace": trace + [{"step": "decide", "action": "emergency"}]}

    if intent == "unknown":
        failures += 1
        state.update({"intent": intent, "slots": slots, "failures": failures, "turns": turns})
        if failures >= 2:
            state["handoff"] = True
            return {"intent": "unknown", "action": "handoff", "risk": "medium", "needs_human": True,
                    "reply": "我连续两次听唔明，已经帮你转家人／姑娘，唔好急。",
                    "slots": slots, "state": state, "trace": trace + [{"step": "decide", "action": "handoff", "reason": "2_failures"}]}
        return {"intent": "unknown", "action": "clarify", "risk": "low", "needs_human": False,
                "reply": "婆婆，我未系好听得明。你可以讲多次，或者按「叫家人」。",
                "slots": slots, "state": state, "trace": trace + [{"step": "decide", "action": "clarify"}]}

    state["failures"] = 0
    missing = _missing(intent, slots)
    if missing:
        state.update({"intent": intent, "slots": slots, "turns": turns})
        return {"intent": intent, "action": "clarify", "risk": "low", "needs_human": False,
                "reply": PROMPTS.get(intent, "可以讲多啲吗？"), "missing": missing,
                "slots": slots, "state": state, "trace": trace + [{"step": "decide", "action": "clarify", "missing": missing}]}

    state.update({"intent": intent, "slots": slots, "turns": turns})
    if intent == "appointment":
        action = "business"
        reply = "我记低你想约 " + str(slots.get("appointment_time")) + "。呢个系预约意向，未真正挂号；我会叫家人／姑娘确认。"
    elif intent == "report":
        action = "summary"
        reply = "我帮你整理今日摘要：血压、用药、复诊同红线，可以播报或发给家人。"
    elif intent == "staff":
        action = "handoff"; state["handoff"] = True
        reply = "好，我帮你叫家人／姑娘，已经记录。"
    elif intent in ("bp", "glucose", "medication", "wound", "fall", "diet"):
        action = "kb"
        reply = "我帮你查一下。"
    else:
        action = "reply"
        reply = "婆婆，我系智能助手，唔系真人。你可以讲血压、用药、复诊或者唔舒服。"
    return {"intent": intent, "action": action, "risk": "low", "needs_human": False,
            "reply": reply, "slots": slots, "state": state,
            "trace": trace + [{"step": "decide", "action": action}]}
