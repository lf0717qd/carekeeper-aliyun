# -*- coding: utf-8 -*-
"""Tiny BM25 retrieval for KB v0.1 draft chunks."""
from __future__ import annotations
import json, math, re, sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
CHUNKS = [json.loads(line) for line in (BASE / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

SYN = {
    "食药": "服药", "吃药": "服药", "食咗药": "服药", "漏食": "漏服", "唔记得食药": "漏服",
    "唞唔到气": "呼吸困难", "透唔到气": "呼吸困难", "气促": "呼吸困难",
    "心口痛": "胸痛", "胸口痛": "胸痛", "心口闷": "胸闷",
    "肚屙": "腹泻", "拉肚子": "腹泻", "屙血": "便血",
    "褥疮": "压力性损伤", "压疮": "压力性损伤",
    "尾龙骨": "骶尾部", "屁股红": "失禁相关性皮炎", "屎尿": "失禁",
    "造口": "肠造口", "造口袋": "造口", "造口周围": "造口",
    "脚黑": "发黑", "脚肿": "水肿", "发烧": "发热", "高烧": "发热",
    "咳": "咳嗽", "呛": "呛咳", "吞唔落": "吞咽困难",
    "加药": "加量", "减药": "减量",
    "管饲": "肠内营养 鼻胃管 胃管", "打果汁": "管饲 鼻胃管", "打药": "管饲 药物",
}


def tokenize(text: str):
    text = (text or "").lower()
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    latin = re.findall(r"[a-z0-9]+", text)
    bigrams = [a + b for a, b in zip(chars, chars[1:])]
    return chars + bigrams + latin


def expand_query(q: str):
    q2 = q
    for k, v in SYN.items():
        if k in q:
            q2 += " " + v
    return q2


docs = []
for c in CHUNKS:
    text = c["title"] + " " + c["section_path"] + " " + c["text"]
    toks = tokenize(text)
    docs.append({"chunk": c, "tf": Counter(toks), "len": len(toks), "title_tf": Counter(tokenize(c["title"] + " " + c["section_path"]))})
N = len(docs)
df = Counter()
for d in docs:
    for t in d["tf"]:
        df[t] += 1
avgdl = sum(d["len"] for d in docs) / max(1, N)


def bm25(q: str, top_k=5, allowed_status=("draft",), home_only=True):
    q = expand_query(q)
    qts = tokenize(q)
    scores = []
    k1, b = 1.5, 0.75
    for d in docs:
        c = d["chunk"]
        if allowed_status and c.get("review_status") not in allowed_status:
            continue
        if home_only and c.get("setting") not in ("home", "home/community", "community"):
            continue
        score = 0.0
        for t in qts:
            if t not in d["tf"]:
                continue
            tf = d["tf"][t]
            idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * d["len"] / avgdl))
        if c.get("risk_level") == "high":
            score += 0.15
        if c.get("topic") in ("wound", "ostomy", "nutrition", "dysphagia"):
            score += 0.05
        # title / section boost
        for t in set(qts):
            if t in d.get("title_tf", {}):
                idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * min(3, d["title_tf"][t]) * 1.6
        # navigation intent boost
        nav_terms = ("家庭病床", "长护", "长护险", "家庭医生", "社区", "申请", "办理", "电话", "地址", "材料", "流程", "转诊")
        if c.get("source_type") == "navigation" and any(k in q for k in nav_terms):
            score += 8
        if "家庭病床" in q and "家庭病床" in c.get("title", ""):
            score += 12
        if score > 0:
            scores.append((score, c))
    scores.sort(key=lambda x: -x[0])
    return [{"score": round(s, 4), **c} for s, c in scores[:top_k]]


RED_RULES = [
    ("胸痛", r"(心口痛|胸口痛|胸痛)"),
    ("呼吸困难", r"(唞唔到气|透唔到气|呼吸困难|气促|嘴唇发紫)"),
    ("意识改变", r"(昏迷|叫唔醒|意识|讲唔清|半边身|中风)"),
    ("跌倒/骨折", r"(跌倒|摔|起唔到身|骨折)"),
    ("出血", r"(大量出血|出血不止|呕血|黑便|流血不止)"),
    ("感染/坏死", r"(发黑|变黑|坏死|有臭味|红肿发热|发烧|高烧|脓毒|休克|见到骨头|皮肤烂|烂晒)"),
    ("低血糖", r"(血糖低|低血糖|出冷汗)"),
    ("呛咳/误吸", r"(呛咳|误吸|窒息|吞唔落)"),
    ("血栓/肺栓塞", r"(小腿肿|单侧.*肿|脚肿.*痛|大腿.*肿|术后.*肿痛)"),
    ("急腹症", r"(腹部剧痛|肚痛到|腹膜炎)"),
    ("血压危象", r"(180/120|血压高.*头痛|血压高.*胸痛|血压高.*气促)"),
]


def rule_red_flag(q: str):
    for name, pat in RED_RULES:
        if re.search(pat, q):
            return {
                "chunk_id": "RULE-REDFLAG",
                "doc_id": "RULE",
                "title": "红线规则（不交给 RAG）",
                "source_type": "rule",
                "setting": "home/community",
                "audience": "family/caregiver",
                "evidence_level": "rule",
                "publish_date": "2026-11-19",
                "effective_date": "2026-11-19",
                "review_status": "approved",
                "quality_flags": [],
                "section_path": "规则层 > " + name,
                "page_start": None,
                "page_end": None,
                "chunk_type": "red_flag",
                "topic": "red_flag",
                "risk_level": "high",
                "answer_policy": "escalate",
                "text": "命中红线：" + name + "。不要继续检索/自由回答；先让老人坐低/保持安全，立即叫家人/家医/120。",
                "citation": "红线规则表 · " + name,
                "score": 999.0,
            }
    return None


def search(q: str, top_k=5, use_rule=True):
    if use_rule:
        r = rule_red_flag(q)
        if r:
            return [r]
    return bm25(q, top_k=top_k)
