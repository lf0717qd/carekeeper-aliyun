# -*- coding: utf-8 -*-
"""Formatting and masking helpers (FR-17)."""
from __future__ import annotations
import re


def mask_id(value: str) -> str:
    s = str(value or "").strip()
    if re.fullmatch(r"\d{17}[\dXx]", s):
        return s[:6] + "********" + s[-4:]
    return s


def mask_phone(value: str) -> str:
    s = str(value or "").strip()
    if re.fullmatch(r"1[3-9]\d{9}", s):
        return s[:3] + "****" + s[-4:]
    return s


def mask_bank_card(value: str) -> str:
    s = str(value or "").strip()
    if re.fullmatch(r"\d{16,19}", s):
        return s[:4] + "********" + s[-4:]
    return s


def mask_sensitive_text(text: str) -> str:
    """Mask IDs/phones/bank cards inside free text; does not touch BP/date."""
    t = str(text or "")
    t = re.sub(r"(?<!\d)(\d{17}[\dXx])(?!\d)", lambda m: mask_id(m.group(1)), t)
    t = re.sub(r"(?<!\d)(1[3-9]\d{9})(?!\d)", lambda m: mask_phone(m.group(1)), t)
    t = re.sub(r"(?<!\d)(\d{16,19})(?!\d)", lambda m: mask_bank_card(m.group(1)), t)
    return t


def format_amount(value, currency: str = "元") -> str:
    try:
        num = float(value)
    except Exception:
        return str(value)
    return f"{num:,.2f} {currency}"


def format_bp(value: str) -> str:
    s = str(value or "").strip()
    m = re.fullmatch(r"(\d{2,3})\s*/\s*(\d{2,3})", s)
    return f"{m.group(1)}/{m.group(2)} mmHg" if m else s


def format_glucose(value, unit: str = "mmol/L") -> str:
    try:
        return f"{float(value):.1f} {unit}"
    except Exception:
        return str(value)


def format_date(value: str) -> str:
    s = str(value or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    return f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日" if m else s


def format_for_speech(value: str) -> str:
    t = str(value or "")
    t = t.replace("mmHg", "毫米汞柱").replace("mmol/L", "毫摩尔每升").replace("mg", "毫克").replace("℃", "度")
    t = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"百分之\1", t)
    t = re.sub(r"(\d{4})-(\d{1,2})-(\d{1,2})", lambda m: f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日", t)
    return t
