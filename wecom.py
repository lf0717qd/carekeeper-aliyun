# -*- coding: utf-8 -*-
"""Minimal WeCom (企业微信) sender: group robot webhook + app text message."""
from __future__ import annotations
import json, time, urllib.parse, urllib.request

_TOKEN = {"token": "", "expires": 0.0, "key": ""}


def _post(url: str, payload: dict, timeout: int = 5) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def send_webhook(url: str, text: str) -> dict:
    """Group robot. URL looks like https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."""
    if not url:
        raise ValueError("empty webhook")
    return _post(url, {"msgtype": "text", "text": {"content": str(text)[:1800]}})


def _access_token(corp_id: str, secret: str) -> str:
    key = corp_id + ":" + secret
    if _TOKEN["key"] == key and _TOKEN["token"] and _TOKEN["expires"] > time.time() + 30:
        return _TOKEN["token"]
    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=" + urllib.parse.quote(corp_id) + "&corpsecret=" + urllib.parse.quote(secret)
    with urllib.request.urlopen(url, timeout=5) as r:
        data = json.loads(r.read().decode("utf-8"))
    if data.get("errcode") != 0:
        raise RuntimeError("wecom gettoken: " + str(data.get("errmsg")))
    _TOKEN.update({"token": data["access_token"], "expires": time.time() + int(data.get("expires_in", 7200)), "key": key})
    return data["access_token"]


def send_app_text(corp_id: str, secret: str, agent_id: str, touser: str, text: str) -> dict:
    """Self-built app outbound text. Requires corp_id/secret/agent_id/touser."""
    token = _access_token(corp_id, secret)
    url = "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=" + urllib.parse.quote(token)
    payload = {
        "touser": touser,
        "msgtype": "text",
        "agentid": int(agent_id),
        "text": {"content": str(text)[:1800]},
        "safe": 0,
    }
    data = _post(url, payload)
    if data.get("errcode") != 0:
        raise RuntimeError("wecom send: " + str(data.get("errmsg")))
    return data
