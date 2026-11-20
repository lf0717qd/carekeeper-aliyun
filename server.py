# -*- coding: utf-8 -*-
"""乡音健康管家 V1.1 Demo 后端。

- 静态文件：index.html / styles.css / app.js / 截图
- GET  /api/health  ：返回 LLM 是否就绪（不暴露 key）
- POST /api/chat    ：粤语健康问答；红线先走规则，再走 LLM
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import secrets
import uuid
from difflib import SequenceMatcher
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    from kb_runtime import search as kb_search
except Exception:
    kb_search = None

try:
    from formatting import mask_sensitive_text, format_for_speech
except Exception:
    def mask_sensitive_text(text):
        return text

try:
    import store
except Exception:
    store = None

try:
    import g2p
except Exception:
    g2p = None


ROOT = Path(__file__).resolve().parent
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("FC_SERVER_PORT", os.getenv("PORT", "9000")))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    text = None
    for encoding in ("utf-8-sig", "utf-8", "gbk", "cp1252"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# 优先读 demo/.env；本地演示回退到 agent-lab/.env；不打印 key
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent.parent / "agent-lab" / ".env")

BASE_URL = os.getenv("BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
MODEL = os.getenv("MODEL", "glm-4-flash")
API_KEY = os.getenv("API_KEY", "")
AUTH_SECRET = os.getenv("AUTH_SECRET", "carekeeper-demo-secret-change-me")
CHAT_REQUIRE_AUTH = os.getenv("CHAT_REQUIRE_AUTH", "1") != "0"
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip()

CHANNELS = {
    "web": {"label": "老人端 Web", "mode": "native", "transport": "HTTPS"},
    "family": {"label": "家属端", "mode": "native", "transport": "HTTPS"},
    "phone": {"label": "电话/IVR", "mode": "adapter_demo", "transport": "SIP/电话网关（未接）"},
    "wechat": {"label": "微信（本期不做）", "mode": "adapter_demo", "transport": "企业微信不采用"},
    "community": {"label": "社区/家医", "mode": "adapter_demo", "transport": "工单/电话（未接）"},
}

DEMO_USERS = {
    "13800000001": {"password": "123456", "role": "elder", "name": "陈婆婆", "patient_ids": ["chen"]},
    "13800000002": {"password": "123456", "role": "family", "name": "陈先生", "patient_ids": ["chen"]},
    "13800000003": {"password": "123456", "role": "doctor", "name": "李医生", "patient_ids": ["chen", "li"]},
    "13800000009": {"password": "123456", "role": "admin", "name": "运营管理员", "patient_ids": []},
}

PATIENTS = {
    "chen": {"id": "chen", "name": "陈婆婆", "age": 76, "area": "广州荔湾",
             "dx": "高血压、2型糖尿病", "bp": "148/86", "med": "2/3",
             "follow": "11-25 09:00 · 社区医院二楼",
             "alerts": [{"t": "今日 08:42", "text": "血压 148/86，已建议静坐复测", "level": "medium", "handled": False},
                        {"t": "昨日 16:10", "text": "漏服一次降压药，已转药师确认", "level": "medium", "handled": True}]},
    "li": {"id": "li", "name": "李伯", "age": 81, "area": "广州越秀",
           "dx": "高血压、慢阻肺", "bp": "132/78", "med": "3/3",
           "follow": "11-28 10:00 · 社区医院",
           "alerts": [{"t": "今日 09:10", "text": "血氧 93%，已建议复测并联系家医", "level": "high", "handled": False}]},
}

if store is not None:
    try:
        store.init(DEMO_USERS, PATIENTS)
    except Exception as exc:  # noqa: BLE001
        print("[store] init failed:", type(exc).__name__, file=sys.stderr)

def make_token(item: dict) -> str:
    payload = {
        "account": item["account"],
        "role": item["role"],
        "name": item["name"],
        "patient_ids": item["patient_ids"],
        "exp": int(time.time()) + 8 * 3600,
        "iat": int(time.time()),
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    sig = hmac.new(AUTH_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return body + "." + sig


def verify_token(token: str):
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(AUTH_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad).decode("utf-8"))
        if int(payload.get("exp", 0)) < time.time():
            return None
        return payload
    except Exception:
        return None


def auth_user_from_header(header: str):
    if not header or not header.startswith("Bearer "):
        return None
    return verify_token(header[7:].strip())


def user_patients(user):
    ids = user.get("patient_ids", [])
    if store is not None:
        try:
            return store.get_patients(ids)
        except Exception:
            pass
    return [PATIENTS[x] for x in ids if x in PATIENTS]
ASR_MODEL = os.getenv("ASR_MODEL", "glm-asr-2512")
ASR_URL = "https://open.bigmodel.cn/api/paas/v4/audio/transcriptions"

RED_FLAGS = [
    "胸痛", "胸口痛", "心口痛", "心口闷", "胸闷", "唞唔到气", "透唔到气", "呼吸困难", "嘴唇发紫",
    "出冷汗", "昏迷", "晕倒", "意识", "叫唔醒", "讲唔清", "半身", "半边身", "偏瘫", "大出血",
    "流血不止", "出血不止", "呕血", "黑便",
    "跌倒", "摔", "起唔到身", "骨折", "跌伤腰", "腰受伤",
    "低血糖", "抽搐",
    "伤口发黑", "脚趾发黑", "皮肤发黑", "坏死", "有臭味", "见到骨头", "红肿发热",
    "呛咳", "误吸", "窒息", "吞唔落",
    "小腿肿", "单侧肿", "脚肿痛", "大腿肿", "术后肿痛",
    "腹部剧痛", "肚痛到", "腹膜炎",
    "180/120", "血压180",
]

SYSTEM_PROMPT = """你系“乡音健康管家”，服务广州广府片嘅居家老人。你只做健康教育、就医引导、用药提醒同复诊提醒，唔做诊断、唔开处方、唔调整药物剂量。

必须遵守：
1. 用粤语口语回答，称呼“婆婆/阿伯”，短句、慢速、先讲结论，最多 120 个中文字。
2. 遇到胸痛、呼吸困难、意识改变、跌倒、低血糖、大出血等红线：risk=high，needs_human=true，回复要叫对方坐低/唔好行，并叫家人/120，唔好自行外出。
3. 药物问题只解释标签、提醒、漏服；强调“唔好自己加量/补双倍”，建议问医生/药师；唔好给具体剂量调整。
4. 唔确定、超出范围、涉及诊断/处方：needs_human=true，建议转家人/家医/人工，唔好硬答。
5. 唔编造政策、药物剂量、检查结果；唔好讲“你得了XX病”。
6. 回答要让人听懂，避免医学术语；必须提醒“呢个只系健康教育，唔系诊断”。
7. 先直接回答用户问题，再给 1-2 条可执行建议；饮食、作息、监测等一般性生活建议可以直接讲（例如份量、搭配、食后测血糖），唔好每次都只讲“问医生”。
8. 饮食问题唔好讲“无问题/随便食”，要讲“可以，但要控制份量/搭配/监测”。
9. 只有涉及诊断、处方、剂量调整、检查结果解释时，才转医生/药师；一般健康教育要给出有用信息。
10. 用户只讲“血压高/血压升”但没有给具体读数时：先问“几多／几多”及有无头痛、胸痛、唞唔到气、睇嘢模糊；唔好先讲药，唔好默认 180/100。
11. 用户没有明确问药时，唔好主动列具体药名、剂量、空腹/饭后/补服建议。
12. 用生活化比喻：血压=水管压力，血糖=血液里的糖，血管=水管，心脏=泵；唔好一开口就讲药名。
13. 用户重复问同一件事时，先讲“你头先问过…”，再补充一个新信息或换一种讲法；唔好原句重复。
14. 如果用户问“食咩药/药名/剂量”，只讲“医生会按情况拣/按药袋食”，唔好列药名、唔好推荐换药。
15. 如果 user_payload 里有 knowledge：只根据 knowledge 回答，引用标题/章节；knowledge 没有的，就讲“我唔确定，帮你问家医/姑娘”，唔好编。

只输出 JSON，不要 markdown，不要解释 JSON：
{"reply":"粤语口语回答","intent":"用药/血压/复诊/症状/其他","risk":"low|medium|high","needs_human":false,"tool_calls":["memory.get_profile"],"follow_up":"下一步建议"}
"""


STREAM_SYSTEM_PROMPT = """你系“乡音健康管家”，服务广州广府片嘅居家老人。你只做健康教育、就医引导、用药提醒同复诊提醒，唔做诊断、唔开处方、唔调整药物剂量。

必须遵守：
1. 只输出一段粤语口语回答，不要 JSON、不要 markdown、不要标题，最多 120 个中文字。
2. 称呼“婆婆/阿伯”，短句、慢速、先讲结论；要让人听得懂。
3. 遇到胸痛、呼吸困难、意识改变、跌倒、低血糖、大出血等红线：叫对方坐低/唔好行，并叫家人/120；唔好自行外出。
4. 药物问题只解释标签、提醒、漏服；强调“唔好自己加量/补双倍”，建议问医生/药师；唔好给剂量调整。
5. 唔确定、涉及诊断/处方：建议转家人/家医/人工，唔好硬答。
6. 饮食问题唔好讲“无问题/随便食”，要讲“可以，但要控制份量/搭配/监测”。
7. 最后必须加一句“呢个只系健康教育，唔系诊断。”
"""

SENSITIVE_URGENT = [
    ("overdose", r"(食多咗|食错药|过量|十粒|安眠药.*多|农药|老鼠药)", "婆婆，唔好再食药。带埋药袋/药盒，立即叫家人同 120；唔好自己催吐。"),
    ("selfharm", r"(唔想活|自杀|跳楼|割腕|结束生命|唔想生存)", "婆婆，你而家安全最重要。唔好一个人，立即叫家人/打120/去急诊；我帮你叫家人。"),
    ("hypoxia", r"(血氧.*(8[0-9]|9[0-4])|血氧低|缺氧)", "婆婆，血氧好低。坐低或者半卧，立即叫家人同 120；唔好自己行。"),
    ("low_glucose", r"(血糖.*(1\.|2\.|3\.[0-2])|血糖低|低血糖)", "婆婆，血糖好低。如果清醒，立即食少量糖/糖水；如果唔清醒/抽搐，唔好喂，立即叫120。"),
    ("high_fever", r"(高烧|发烧.*(39|40)|39度|40度)", "婆婆，高烧要即刻处理。坐低休息，叫家人/120；唔好自己乱食药。"),
    ("hemoptysis", r"(咳血|吐血|呕血)", "婆婆，咳血/呕血唔好等。坐低，立即叫家人同120；唔好自己走出去。"),
    ("head_injury", r"(跌亲头|撞到头|头先落地|头部受伤)", "婆婆，跌亲头又呕，唔好乱动。坐低/平卧，立即叫家人同120。"),
    ("child_seizure", r"((个孙|小朋友|婴儿|BB).*(抽筋|抽搐|高烧)|(抽筋|抽搐).*(个孙|小朋友|婴儿|BB))", "婆婆，小朋友抽筋/高烧，立即侧卧，唔好塞东西入口，叫120；唔好按人中。"),
    ("abuse", r"(打我|家暴|虐待|个仔.*打|唔好同人讲.*打)", "婆婆，如果你而家有人身危险，先离开/锁门，打110或120，揾可信任嘅人；唔好一个人。"),
]

SENSITIVE_REFUSE = [
    ("privacy", r"(查下.*(食咩药|病历|报告)|隔离.*(食咩药|病历)|帮我查.*(药|病历))", "我唔可以查其他人嘅药/病历；只可以帮本人或已授权家属。"),
    ("fraud", r"(假病历|假假条|开假|改报告|伪造)", "我唔可以写假病历/假假条；呢个涉及违法。"),
    ("prescription", r"(帮我开|开两盒|开抗生素|开药|处方|打针|输液)", "我唔可以开药/开抗生素/处方；请医生/药师。"),
    ("diagnosis", r"(系咪.*(癌|恶性|痴呆|病)|帮我睇.*报告|确诊)", "我唔可以确诊；带报告/病历给医生睇。"),
    ("dose", r"(加一粒|减一粒|加药|减药|停药|食几多|食多少|几粒|剂量|自己调|调胰岛素)", "我唔可以教你加药/减药/停药/调剂量；按药袋/医生吩咐，问医生/药师。"),
    ("pregnancy", r"((大肚|怀孕|孕妇).*(药|降压|食)|(药|降压).*(大肚|怀孕|孕妇))", "大肚用药要医生/药师评估；我唔可以推荐药。"),
    ("interaction", r"((薄血药|华法林|阿司匹林|氯吡格雷|抗凝).*(食|同食|可以)|(食|同食|可以).*(薄血药|华法林|阿司匹林|氯吡格雷))", "药物相互作用要问医生/药师，我唔可以答可以/唔可以。"),
]

def safety_reply(text: str):
    for kind, pat, reply in SENSITIVE_URGENT:
        if re.search(pat, text):
            return {
                "reply": reply + " 呢个只系安全教育，唔系诊断。",
                "intent": "安全/红线",
                "risk": "high",
                "needs_human": True,
                "tool_calls": ["safety." + kind, "escalate.120"],
                "follow_up": "保持在线，等家人/救护车；不要自行外出。",
                "source": "rule_safety",
            }
    if has_red_flag(text):
        return None
    for kind, pat, reply in SENSITIVE_REFUSE:
        if re.search(pat, text):
            return {
                "reply": reply + " 呢个只系健康教育，唔系诊断。",
                "intent": "安全边界",
                "risk": "medium",
                "needs_human": True,
                "tool_calls": ["safety." + kind],
                "follow_up": "请医生/药师/家属确认。",
                "source": "rule_safety",
            }
    return None

FRAUD_PATTERNS = [
    ("中奖", r"(中奖|抽中.*奖|领奖|奖金)"),
    ("安全账户", r"(安全账户|安全账号|资金审查|清查账户)"),
    ("公检法", r"(公检法|公安.*(办案|洗钱|通缉)|检察院.*(调查|传票)|法院.*传票|通缉)"),
    ("诱导转账", r"((转账|汇款|打款).*(安全|陌生|客服|公安|检察院|法院|中奖|投资|保证金|手续费|刷单)|(安全|陌生|客服|公安|检察院|法院|中奖|投资|保证金|手续费|刷单).*(转账|汇款|打款)|验证码.*(客服|退款|银行|公安|陌生|转账))"),
    ("刷单", r"(刷单|返利|做任务.*钱|兼职.*佣金)"),
    ("养老投资", r"(养老投资|高回报|保本高息|以房养老|投资项目.*老人)"),
    ("神药", r"(包治|神药|根治|保健品.*治|专家.*推荐.*药)"),
    ("冒充客服", r"(客服.*退款|快递.*赔|社保.*停|医保.*停)"),
]

def fraud_reply(text: str):
    for kind, pat in FRAUD_PATTERNS:
        if re.search(pat, text):
            return {
                "reply": "婆婆，呢啲多数系骗案。唔好转账、唔好俾验证码、唔好买；即刻挂线，打110或者叫家人帮手。",
                "intent": "防诈骗",
                "risk": "high",
                "needs_human": True,
                "tool_calls": ["safety.scam", "escalate.110"],
                "follow_up": "不要转账/给验证码；联系家人或110。",
                "source": "rule_fraud",
            }
    return None

def money_safety_reply(text: str):
    if not re.search(r"(转账|汇款|打款|银行卡|验证码|押金)", text):
        return None
    if "验证码" in text:
        reply = "验证码唔好俾任何人，包括自称客服、公安或者银行嘅人。有疑问挂线，打110或者叫家人帮手。"
        follow = "不要给验证码；挂线；打110/叫家人。"
    elif re.search(r"(医院|住院|押金|缴费)", text):
        reply = "医院缴费行正式窗口或者对公账户，唔好转个人账户。有疑问打医院总机，或者叫家人陪你核实。"
        follow = "医院缴费走窗口/对公账户；不转个人账户。"
    elif re.search(r"(医保|报销)", text):
        reply = "医保报销用银行卡通常正常，但只交给医保局、社区或者医院正式渠道，唔好俾陌生人，也唔好俾验证码。"
        follow = "只走医保/社区/医院正式渠道；不给陌生人/验证码。"
    else:
        reply = "钱银转账我唔帮你操作。同家人或者银行确认，唔好向陌生账户转；怀疑骗案打110。"
        follow = "不向陌生账户转账；同家人/银行确认。"
    return {
        "reply": reply,
        "intent": "钱银安全",
        "risk": "medium",
        "needs_human": True,
        "tool_calls": ["safety.money"],
        "follow_up": follow,
        "source": "rule_money_safety",
    }

MYTH_PATTERNS = [
    ("喝醋软化血管", r"(醋.*软化血管|软化血管.*醋)"),
    ("输液通血管", r"(输液.*通血管|通血管.*输液)"),
    ("保健品根治", r"(保健品.*根治|偏方.*根治|吃.*保健品.*停药)"),
    ("饿死癌细胞", r"(饿死.*癌|唔食饭.*癌|不吃饭.*癌)"),
]

def myth_reply(text: str):
    for kind, pat in MYTH_PATTERNS:
        if re.search(pat, text):
            if kind == "喝醋软化血管":
                reply = "婆婆，醋唔会软化血管，呢个系偏方。血压高要按医生药、少盐、复诊；胃唔好更唔好空腹饮醋。"
                follow = "不要靠喝醋软化血管；按医嘱服药/复诊。"
            elif kind == "输液通血管":
                reply = "输液唔可以通血管，反而有风险。血管问题要医生评估，唔好去没资质的地方吊针。"
                follow = "不要靠输液通血管；看医生。"
            elif kind == "饿死癌细胞":
                reply = "唔可以靠饿死癌细胞。唔食饭会营养不良、抵抗力更差；要按医生/营养师嘅方案食，唔好自己戒口。"
                follow = "不要靠不吃饭饿死癌细胞；按医生/营养师。"
            else:
                reply = "保健品/偏方唔可以根治慢性病，也唔可以代替医生药。唔好自己停药；有疑问问医生/药师。"
                follow = "保健品不替代药物；不自行停药。"
            return {
                "reply": reply,
                "intent": "健康辟谣",
                "risk": "medium",
                "needs_human": False,
                "tool_calls": ["safety.myth"],
                "follow_up": follow,
                "source": "rule_myth",
            }
    return None

def send_alert(event: str, **fields) -> None:
    """Optional Feishu/DingTalk webhook; metadata only, no raw message."""
    url = ALERT_WEBHOOK_URL
    if not url:
        return
    parts = ["[乡音健康管家]", event]
    for key in ("request_id", "source", "risk", "needs_human", "intent", "error"):
        if key in fields and fields[key] not in (None, ""):
            parts.append(f"{key}={fields[key]}")
    text = " ".join(parts)
    if "feishu" in url or "larksuite" in url:
        payload = {"msg_type": "text", "content": {"text": text}}
    elif "dingtalk" in url:
        payload = {"msgtype": "text", "text": {"content": text}}
    else:
        payload = {"event": event, "text": text, **{k: v for k, v in fields.items() if k in ("request_id", "source", "risk", "needs_human", "intent", "error")}}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=3).read()
    except Exception as exc:  # noqa: BLE001
        print("[alert] webhook error:", type(exc).__name__, file=sys.stderr)


def audit_event(event: str, **fields) -> None:
    """Structured audit line; never include raw message/audio/query."""
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event}
    for key, value in fields.items():
        if key in ("message", "query", "audio_base64", "reply"):
            continue
        record[key] = value
    print("[audit] " + json.dumps(record, ensure_ascii=False, separators=(",", ":")), flush=True)


COGNITIVE_PATTERN = r"(记性差|脑退化|认知障碍|痴呆|唔认得人|迷路)"

def cognitive_reply(text: str):
    if re.search(COGNITIVE_PATTERN, text):
        return {
            "reply": "婆婆，记性差有好多原因，唔一定系脑退化。建议去医生或者记忆门诊评估；屋企注意防走失、防跌倒，药物最好由家人保管；如果突然好混乱、发烧或者脱水，尽快就医。",
            "intent": "认知担忧",
            "risk": "medium",
            "needs_human": True,
            "tool_calls": ["safety.cognitive"],
            "follow_up": "建议医生/记忆门诊评估；防走失、防跌倒；突然混乱/发烧尽快就医。",
            "source": "rule_cognitive",
        }
    return None

def has_red_flag(text: str) -> bool:
    return any(word in text for word in RED_FLAGS)


def extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    text = re.sub(r"^\x60{3}(?:json)?", "", text).strip()
    text = re.sub(r"\x60{3}$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def fallback(message: str, reason: str = "") -> dict:
    if has_red_flag(message):
        reply = "婆婆，你而家唔好行，坐低或者半躺。我帮你叫家人同 120。你保持同我讲嘢，唔好自己走出去。"
        return {
            "reply": reply,
            "intent": "红线",
            "risk": "high",
            "needs_human": True,
            "tool_calls": ["triage.red_flag", "escalate.120", "notify.family"],
            "follow_up": "保持在线，等家人/救护车；不要自行外出。",
            "source": "rule",
            "reason": reason,
        }
    return {
        "reply": "婆婆，我而家未系好听得明。你可以讲多次，或者我帮你叫家人/姑娘。",
        "intent": "未识别",
        "risk": "low",
        "needs_human": True,
        "tool_calls": ["human.takeover"],
        "follow_up": "转家人/人工确认。",
        "source": "fallback",
        "reason": reason,
    }


BP_VARIANTS = [
    "婆婆，血压高即系血管压力大。你有冇量到几多／几多？有冇头痛、胸痛、唞唔到气、睇嘢模糊？唔好自己加药，坐低休息十分钟再量。",
    "婆婆，先坐低慢慢讲。你今日量到几多／几多？有冇头痛、心口痛、气促？血压高唔好自己加药，等阵复测。",
    "婆婆，血压高要睇读数同症状。你而家量到几多／几多？有冇唔舒服？先休息十分钟，再量一次。",
]


def med_plain_reply(message: str) -> dict | None:
    if not re.search(r"(药|服药|食药|漏服|加药|减药|药名|药袋|药盒)", message):
        return None
    if re.search(r"(食咩药|食什么药|边只药|药名|推荐.*药|换药|加药|减药|剂量|食几多|打几多)", message):
        return {
            "reply": "婆婆，降压药、降糖药有好多类，医生会按你血压、血糖、肾同心脏情况拣，我唔会帮你换药或介绍药名。你药袋上嗰只继续按吩咐食，唔好自己加减；唔舒服就问医生/药师。",
            "intent": "用药", "risk": "medium", "needs_human": True,
            "tool_calls": ["policy.medication_boundary", "escalate.pharmacist"],
            "follow_up": "只按标签/医嘱；不自行加量、减量、补双倍。",
            "source": "rule_plain", "reason": "用药问题不列药名/不调剂量",
        }
    if re.search(r"(漏服|唔记得|漏食|忘记)", message):
        return {
            "reply": "婆婆，漏咗一次唔好补双倍，下次按原本时间食。你药袋上嗰只药如果唔确定，就影张相问家人/药师，唔好自己加。",
            "intent": "用药", "risk": "medium", "needs_human": True,
            "tool_calls": ["policy.missed_dose", "escalate.pharmacist"],
            "follow_up": "不补双倍；问药师/医生。",
            "source": "rule_plain", "reason": "漏服边界",
        }
    return {
        "reply": "婆婆，药要按药袋/医生吩咐食，我唔会帮你调剂量。你食完有冇头晕、心慌、肚唔舒服？有就同我讲，我帮你问医生/药师。",
        "intent": "用药", "risk": "medium", "needs_human": True,
        "tool_calls": ["policy.medication_boundary"],
        "follow_up": "观察不适；问医生/药师。",
        "source": "rule_plain", "reason": "用药问题简答",
    }


def bp_reading_reply(message: str, history: list[dict] | None = None) -> dict | None:
    if not re.search(r"血压\s*(高|升|又高)", message):
        return None
    if re.search(r"(食咩药|药名|边只药|换药|加药|减药|剂量)", message):
        return None
    match = re.search(r"(\d{2,3})\s*[/／]\s*(\d{2,3})", message)
    if not match:
        idx = (len(history or []) // 2) % len(BP_VARIANTS)
        return {
            "reply": BP_VARIANTS[idx], "intent": "血压", "risk": "medium", "needs_human": True,
            "tool_calls": ["triage.bp_reading", "memory.get_vitals"],
            "follow_up": "先复测；如果读数 >=180/120 或伴胸痛/气促/神经症状，立即叫家人/120。",
            "source": "rule_plain", "reason": "血压高但未提供读数",
        }
    systolic, diastolic = int(match.group(1)), int(match.group(2))
    urgent = systolic >= 180 or diastolic >= 120
    reply = "婆婆，" + str(systolic) + "/" + str(diastolic) + " 偏高。你先坐低休息十分钟再量；如果高过180/120，或者有胸痛、气促、头痛、睇嘢模糊，立即叫家人/120。唔好自己加药。"
    if urgent:
        reply = "婆婆，" + str(systolic) + "/" + str(diastolic) + " 好高，唔好等。你而家坐低，唔好行，我帮你叫家人/120；如果有胸痛、气促、讲唔清，立即讲。"
    return {
        "reply": reply, "intent": "血压", "risk": "high" if urgent else "medium", "needs_human": True,
        "tool_calls": ["triage.bp_reading", "escalate.120" if urgent else "notify.family"],
        "follow_up": "复测并记录；>=180/120 或伴症状立即就医。",
        "source": "rule_plain", "reason": "血压读数处理",
    }


def last_assistant_text(history: list[dict] | None) -> str:
    for item in reversed(history or []):
        if item.get("role") == "assistant":
            return str(item.get("content", "")).strip()
    return ""


def dedupe_reply(reply: str, message: str, history: list[dict] | None) -> str:
    last = last_assistant_text(history)
    if not last:
        return reply
    norm = lambda x: re.sub(r"[\s，。！？、；：,.!?;:]+", "", x or "")
    if SequenceMatcher(None, norm(reply), norm(last)).ratio() < 0.78:
        return reply
    if re.search(r"(食粥|食饭|饮食|食乜|食咩)", message):
        return "婆婆，你头先问过食粥。可以食，但份量半碗左右，配菜或者蛋白质，食后两小时测血糖；如果血糖高过平时，就同我讲。"
    if re.search(r"(药|服药|食药)", message):
        return "婆婆，你头先问过药。你药袋上嗰只继续按吩咐食，唔好自己加减；最近有冇漏食、头晕或者肚唔舒服？"
    return "婆婆，你头先问过呢个问题，我换个讲法：" + reply


def ask_llm(message: str, profile: dict, history: list[dict]) -> dict:
    if not API_KEY:
        return fallback(message, "API_KEY 未配置")

    # 辟谣优先于“不能开药”的拒答；但有红线或明显骗案词时让位
    if not has_red_flag(message):
        myth = myth_reply(message)
        scam_words = r"(中奖|转账|安全账户|公检法|验证码|客服.*退款|刷单|投资|免费|讲座|推销)"
        if myth and not re.search(scam_words, message):
            return myth

    # 红线不交给 LLM，直接走规则
    safety = safety_reply(message)
    if safety:
        return safety
    if has_red_flag(message):
        return fallback(message, "红线规则命中")

    fraud = fraud_reply(message)
    if fraud:
        return fraud
    money = money_safety_reply(message)
    if money:
        return money
    myth = myth_reply(message)
    if myth:
        return myth
    cognitive = cognitive_reply(message)
    if cognitive:
        return cognitive

    bp_reply = bp_reading_reply(message, history)
    if bp_reply:
        bp_reply["reply"] = dedupe_reply(bp_reply["reply"], message, history)
        return bp_reply

    med_reply = med_plain_reply(message)
    if med_reply:
        med_reply["reply"] = dedupe_reply(med_reply["reply"], message, history)
        return med_reply

    kb_items = []
    if kb_search:
        try:
            kb_items = kb_search(message, top_k=3, use_rule=False)
        except Exception:
            kb_items = []
    knowledge = []
    for item in kb_items:
        if item.get("risk_level") == "high" or item.get("answer_policy") == "refuse":
            continue
        knowledge.append({
            "title": item.get("title", ""),
            "section": item.get("section_path", ""),
            "page": item.get("page_start"),
            "text": str(item.get("text", ""))[:500],
            "citation": item.get("citation", ""),
        })
    citations = list(dict.fromkeys([k["citation"] for k in knowledge]))

    recent = []
    for item in (history or [])[-6:]:
        role = item.get("role")
        content = str(item.get("content", ""))[:400]
        if role in ("user", "assistant") and content:
            recent.append({"role": role, "content": content})

    user_payload = json.dumps(
        {"message": message, "profile": profile, "recent": recent, "knowledge": knowledge},
        ensure_ascii=False,
    )
    started = time.time()
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_payload},
        ],
        "temperature": 0.4,
        "max_tokens": 320,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Authorization": "Bearer " + API_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        payload = json.loads(response.read().decode("utf-8"))
    raw = payload["choices"][0]["message"].get("content", "") or ""
    data = extract_json(raw)
    elapsed = round((time.time() - started) * 1000)

    if not data or not data.get("reply"):
        result = fallback(message, "LLM 返回非 JSON")
        result["raw"] = raw[:500]
        result["latency_ms"] = elapsed
        result["source"] = "llm_parse_fallback"
        return result

    result = {
        "reply": str(data.get("reply", ""))[:500],
        "intent": str(data.get("intent", "其他"))[:40],
        "risk": str(data.get("risk", "low"))[:10],
        "needs_human": bool(data.get("needs_human", False)),
        "tool_calls": data.get("tool_calls", []) if isinstance(data.get("tool_calls"), list) else [],
        "follow_up": str(data.get("follow_up", ""))[:200],
        "source": "llm",
        "model": MODEL,
        "latency_ms": elapsed,
        "citations": citations,
    }
    if "唔系诊断" not in result["reply"] and "不是诊断" not in result["reply"]:
        result["reply"] = result["reply"].rstrip("。") + "。呢个只系健康教育，唔系诊断。"
    result["reply"] = dedupe_reply(result["reply"], message, history)
    return result


def stream_llm(message: str, profile: dict, history: list[dict]):
    """FC 版本先用非流式结果包装成 SSE，前端仍可正常显示。"""
    started = time.time()
    data = ask_llm(message, profile, history)
    yield "meta", {"source": data.get("source", "llm"), "model": MODEL, "risk": data.get("risk", "low"), "needs_human": data.get("needs_human", False)}
    yield "delta", {"text": mask_sensitive_text(data.get("reply", ""))}
    yield "done", {
        "source": data.get("source", "llm"),
        "risk": data.get("risk", "low"),
        "needs_human": data.get("needs_human", False),
        "intent": data.get("intent", "其他"),
        "latency_ms": round((time.time() - started) * 1000),
        "citations": data.get("citations", []),
    }


def transcribe(audio_base64: str) -> dict:
    if not API_KEY:
        raise RuntimeError("API_KEY 未配置")
    if not audio_base64:
        raise ValueError("audio_base64 为空")
    raw = base64.b64decode(audio_base64, validate=False)
    if len(raw) > 25 * 1024 * 1024:
        raise ValueError("音频超过 25MB")
    body = json.dumps({
        "model": ASR_MODEL,
        "file_base64": audio_base64,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        ASR_URL,
        data=body,
        headers={
            "Authorization": "Bearer " + API_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {
        "text": str(payload.get("text", "")).strip(),
        "model": ASR_MODEL,
        "latency_ms": round((time.time() - started) * 1000),
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Request-ID")
        self.send_header("Access-Control-Max-Age", "86400")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _admin_user(self):
        user = auth_user_from_header(self.headers.get("Authorization", ""))
        if not user:
            self._json(401, {"error": "unauthorized"})
            return None
        if user.get("role") != "admin":
            self._json(403, {"error": "admin only"})
            return None
        return user

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/admin/overview":
            if not self._admin_user():
                return
            self._json(200, store.admin_overview())
            return
        if path == "/api/auth/me":
            user = auth_user_from_header(self.headers.get("Authorization", ""))
            if not user:
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, {"role": user["role"], "name": user["name"], "account": user["account"], "patient_ids": user["patient_ids"]})
            return
        if path == "/api/app/patients":
            user = auth_user_from_header(self.headers.get("Authorization", ""))
            if not user:
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, {"patients": user_patients(user)})
            return
        if path == "/api/channels":
            self._json(200, {"channels": [{"id": k, **v} for k, v in CHANNELS.items()]})
            return
        if path == "/api/health":
            self._json(200, {
                "ok": bool(API_KEY),
                "model": MODEL,
                "base_url": BASE_URL,
                "has_key": bool(API_KEY),
            })
            return
        return super().do_GET()

    def _stream(self, payload: dict) -> None:
        message = str(payload.get("message", "")).strip()
        profile = payload.get("profile") or {}
        history = payload.get("history") or []
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for event, data in stream_llm(message, profile, history):
                chunk = "event: " + event + "\ndata: " + json.dumps(data, ensure_ascii=False) + "\n\n"
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            print("[stream] client disconnected", file=sys.stderr)

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/chat", "/api/chat_stream", "/api/asr", "/api/kb/search", "/api/audit/event", "/api/format", "/api/channel/message", "/api/auth/login", "/api/auth/logout", "/api/app/chat", "/api/pronounce", "/api/admin/feedback", "/api/admin/templates", "/api/admin/annotations", "/api/admin/releases", "/api/admin/terms"):
            self._json(404, {"error": "not found"})
            return
        request_id = self.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if path == "/api/pronounce":
                text = str(payload.get("text", "")).strip()
                if not text:
                    self._json(400, {"error": "text required"})
                    return
                if g2p is None:
                    self._json(501, {"error": "g2p not available"})
                    return
                try:
                    result = g2p.pronounce(text)
                except Exception as exc:  # noqa: BLE001
                    self._json(500, {"error": "g2p failed: " + type(exc).__name__})
                    return
                self._json(200, result)
                return
            if path in ("/api/admin/feedback", "/api/admin/templates", "/api/admin/annotations", "/api/admin/releases", "/api/admin/terms"):
                user = self._admin_user()
                if not user:
                    return
                if path == "/api/admin/feedback":
                    store.update_feedback(int(payload.get("id", 0)), str(payload.get("status", "done")), str(payload.get("follow_up", ""))[:120])
                elif path == "/api/admin/templates":
                    store.save_template(int(payload.get("id", 0)), bool(payload.get("active", True)))
                elif path == "/api/admin/annotations":
                    store.update_annotation(int(payload.get("id", 0)), str(payload.get("status", "done")), str(payload.get("label", ""))[:40], str(payload.get("note", ""))[:120])
                elif path == "/api/admin/releases":
                    if payload.get("version"):
                        store.add_release(str(payload["version"])[:20], int(payload.get("percent", 10)), str(payload.get("note", ""))[:80])
                    else:
                        store.set_release(int(payload.get("id", 0)), str(payload.get("status", "stable")), payload.get("percent"))
                elif path == "/api/admin/terms":
                    store.review_term(int(payload.get("id", 0)), str(payload.get("status", "approved")), str(payload.get("note", ""))[:120])
                audit_event("admin.action", request_id=request_id, role="admin", action=path.rsplit("/", 1)[-1])
                self._json(200, {"ok": True, "overview": store.admin_overview()})
                return
            if path == "/api/auth/login":
                account = str(payload.get("account", "")).strip()
                password = str(payload.get("password", ""))
                item = (store.get_user(account) if store is not None else None) or DEMO_USERS.get(account)
                if not item or item["password"] != password:
                    audit_event("auth.login_failed", request_id=request_id, account_hash=hashlib.sha256(account.encode("utf-8")).hexdigest()[:12])
                    self._json(401, {"error": "account or password incorrect"})
                    return
                sess = {"account": account, "role": item["role"], "name": item["name"], "patient_ids": item["patient_ids"]}
                token = make_token(sess)
                audit_event("auth.login", request_id=request_id, role=item["role"], account_hash=hashlib.sha256(account.encode("utf-8")).hexdigest()[:12])
                self._json(200, {"token": token, "role": item["role"], "name": item["name"], "patient_ids": item["patient_ids"]})
                return
            if path == "/api/auth/logout":
                user = auth_user_from_header(self.headers.get("Authorization", ""))
                if user:
                    audit_event("auth.logout", request_id=request_id, role=user["role"])
                self._json(200, {"ok": True})
                return
            if path == "/api/app/chat":
                user = auth_user_from_header(self.headers.get("Authorization", ""))
                if not user:
                    self._json(401, {"error": "unauthorized"})
                    return
                patient_id = str(payload.get("patient_id", "")).strip()
                if patient_id not in user["patient_ids"]:
                    audit_event("app.chat_denied", request_id=request_id, role=user["role"], patient_id=patient_id)
                    self._json(403, {"error": "patient not allowed"})
                    return
                message = str(payload.get("message", "")).strip()
                if not message:
                    self._json(400, {"error": "message required"})
                    return
                result = ask_llm(message, {"name": PATIENTS[patient_id]["name"]}, payload.get("history") or [])
                result["reply"] = mask_sensitive_text(result.get("reply", ""))
                result["patient_id"] = patient_id
                audit_event("app.chat", request_id=request_id, role=user["role"], patient_id=patient_id, source=result.get("source"), risk=result.get("risk"), needs_human=result.get("needs_human"))
                self._json(200, result)
                return
            if path == "/api/channel/message":
                channel = str(payload.get("channel", "web")).strip().lower()
                if channel not in CHANNELS:
                    self._json(400, {"error": "unknown channel"})
                    return
                message = str(payload.get("message", "")).strip()
                if not message:
                    self._json(400, {"error": "message required"})
                    return
                profile = payload.get("profile") or {}
                history = payload.get("history") or []
                user_key = str(payload.get("user_id", request_id))[:80]
                session_id = channel + ":" + hashlib.sha256(user_key.encode("utf-8")).hexdigest()[:12]
                result = ask_llm(message, profile, history)
                result["reply"] = mask_sensitive_text(result.get("reply", ""))
                result.update({
                    "channel": channel,
                    "channel_label": CHANNELS[channel]["label"],
                    "channel_mode": CHANNELS[channel]["mode"],
                    "session_id": session_id,
                    "handoff": {
                        "needed": bool(result.get("risk") == "high" or result.get("needs_human")),
                        "target": "120/家属/值班" if result.get("risk") == "high" else "家属/社区",
                        "status": "simulated",
                    },
                })
                audit_event("channel.message", request_id=request_id, channel=channel,
                            session_id=session_id, message_len=len(message),
                            message_hash=hashlib.sha256(message.encode("utf-8")).hexdigest()[:12],
                            source=result.get("source"), risk=result.get("risk"),
                            needs_human=result.get("needs_human"))
                self._json(200, result)
                return
            if path == "/api/format":
                text = str(payload.get("text", ""))[:2000]
                masked = mask_sensitive_text(text)
                self._json(200, {"ok": True, "raw_len": len(text), "masked": masked, "speech": format_for_speech(masked)})
                return
            if path == "/api/audit/event":
                event = str(payload.get("event", "")).strip()
                allowed = {"consent.authorize", "consent.revoke", "privacy.delete", "report.send", "ai.identity"}
                if event not in allowed:
                    self._json(400, {"error": "event not allowed"})
                    return
                action = str(payload.get("action", ""))[:40]
                detail = str(payload.get("detail", ""))[:80]
                audit_event("frontend.audit", request_id=request_id, client_event=event, action=action,
                            detail_hash=hashlib.sha256(detail.encode("utf-8")).hexdigest()[:12])
                self._json(200, {"ok": True})
                return
            if path == "/api/asr":
                result = transcribe(str(payload.get("audio_base64", "")))
                self._json(200, result)
                return
            if path == "/api/kb/search":
                query = str(payload.get("query", "")).strip()
                if not query:
                    self._json(400, {"error": "query required"})
                    return
                try:
                    top_k = int(payload.get("top_k", 5))
                except Exception:
                    top_k = 5
                top_k = max(1, min(10, top_k))
                results = kb_search(query, top_k=top_k, use_rule=True) if kb_search else []
                audit_event("kb.search", request_id=request_id, query_len=len(query), query_hash=hashlib.sha256(query.encode("utf-8")).hexdigest()[:12], count=len(results))
                self._json(200, {"query": query, "count": len(results), "results": results})
                return
            if path in ("/api/chat", "/api/chat_stream") and CHAT_REQUIRE_AUTH:
                user = auth_user_from_header(self.headers.get("Authorization", ""))
                if not user:
                    self._json(401, {"error": "unauthorized"})
                    return
            message = str(payload.get("message", "")).strip()
            if not message:
                self._json(400, {"error": "message required"})
                return
            if path == "/api/chat_stream":
                self._stream(payload)
                return
            profile = payload.get("profile") or {}
            history = payload.get("history") or []
            result = ask_llm(message, profile, history)
            result["reply"] = mask_sensitive_text(result.get("reply", ""))
            audit_event("chat.response", request_id=request_id, message_len=len(message), message_hash=hashlib.sha256(message.encode("utf-8")).hexdigest()[:12], source=result.get("source"), risk=result.get("risk"), needs_human=result.get("needs_human"), intent=result.get("intent"))
            if result.get("risk") == "high":
                audit_event("alert.high_risk", request_id=request_id, source=result.get("source"), risk="high", needs_human=result.get("needs_human"), intent=result.get("intent"))
                send_alert("alert.high_risk", request_id=request_id, source=result.get("source"), risk="high", needs_human=result.get("needs_human"), intent=result.get("intent"))
            self._json(200, result)
        except Exception as exc:  # noqa: BLE001
            print("[api] error:", repr(exc), file=sys.stderr)
            audit_event("api.error", request_id=request_id, error=type(exc).__name__)
            audit_event("alert.api_error", request_id=request_id, error=type(exc).__name__)
            send_alert("alert.api_error", request_id=request_id, error=type(exc).__name__)
            self._json(200, fallback("", "服务异常: " + type(exc).__name__))

    def log_message(self, fmt: str, *args) -> None:
        print("[http] " + fmt % args, file=sys.stderr)


def main() -> None:
    print(f"[boot] {ROOT}")
    print(f"[boot] model={MODEL} base={BASE_URL} key={'set' if API_KEY else 'missing'}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[boot] http://{HOST}:{PORT}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
