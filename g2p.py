# -*- coding: utf-8 -*-
"""Cantonese G2P wrapper. Bundled ToJyutping is BSD-2-Clause."""
from __future__ import annotations

try:
    import ToJyutping
except Exception:
    ToJyutping = None


def available() -> bool:
    return ToJyutping is not None


def pronounce(text: str, limit: int = 200):
    text = str(text or "").strip()[:limit]
    if not text:
        return {"text": "", "jyutping": "", "syllables": []}
    if ToJyutping is None:
        raise RuntimeError("ToJyutping not installed")
    rows = ToJyutping.get_jyutping_list(text)
    return {
        "text": text,
        "jyutping": ToJyutping.get_jyutping_text(text),
        "syllables": [{"char": ch, "jyutping": jp} for ch, jp in rows],
    }
