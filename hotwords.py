# -*- coding: utf-8 -*-
"""Post-ASR hotword correction. Does not change the ASR request."""
from __future__ import annotations
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULT = [
    ("换骗", "换片"), ("换遍", "换片"), ("换偏", "换片"),
    ("尿骗", "尿片"), ("尿遍", "尿片"),
    ("心医", "心翳"), ("心依", "心翳"),
    ("脑退话", "脑退化"), ("脑退发", "脑退化"),
    ("甜尿病", "糖尿病"),
    ("压苍", "压疮"), ("压窗", "压疮"),
]
_LEXICON = None


def lexicon():
    global _LEXICON
    if _LEXICON is None:
        try:
            rows = json.loads((BASE / "cantonese_terms.json").read_text(encoding="utf-8"))
            _LEXICON = sorted({str(r.get("term", "")) for r in rows if len(str(r.get("term", ""))) >= 2}, key=len, reverse=True)
        except Exception:
            _LEXICON = []
    return _LEXICON


def apply(text: str, corrections=None) -> dict:
    raw = str(text or "").strip()
    pairs = list(DEFAULT)
    for row in corrections or []:
        if row.get("active", 1) and row.get("wrong") and row.get("right"):
            pairs.append((str(row["wrong"]), str(row["right"])))
    # longest wrong first to avoid partial overlaps
    seen = set()
    ordered = []
    for wrong, right in sorted(pairs, key=lambda x: len(x[0]), reverse=True):
        if wrong and wrong not in seen:
            seen.add(wrong)
            ordered.append((wrong, right))
    out = raw
    changes = []
    for wrong, right in ordered:
        if wrong in out:
            out = out.replace(wrong, right)
            changes.append({"from": wrong, "to": right})
    hits = [t for t in lexicon() if t in raw or t in out]
    return {"raw_text": raw, "text": out, "corrections": changes, "hotwords": hits}
