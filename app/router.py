from __future__ import annotations

import base64
import ast
import operator
import json
import re
import time
import uuid
from decimal import Decimal
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Response

from .agent_tools import build_tool_planner_prompt, enforce_tool_plan, parse_tool_plan, weather_context_with_repair
from .config import read_config_file, reload_settings, save_config_file, settings
from .models import WechatBridgeResponse, WechatImageCacheRequest, WechatIntentRequest, WechatMessageRequest
from .providers import ProviderError, build_intent_system_prompt, client, parse_intent
from .state import bridge_state


router = APIRouter()
CHAT_NOTICE_TEXT = "正在核对信息，稍后回复。"

_DRAW_PREFIXES = (
    "/生图 ", "/绘图 ", "/画图 ", "/作图 ",
    "生图 ", "绘图 ", "画图 ", "作图 ",
)
_CHAT_PREFIXES = (
    "/聊天 ", "/问 ", "聊天 ", "问 ",
)
_DRAW_RE = re.compile(
    r"(画|绘制|生成|做|设计|创作|制作).{0,20}(图|图片|图像|海报|头像|插画|壁纸|封面|logo|标志)"
    r"|(图|图片|图像|海报|头像|插画|壁纸|封面|logo|标志).{0,20}(画|绘制|生成|做|设计|创作|制作)",
    re.IGNORECASE,
)
_SIMPLE_DRAW_RE = re.compile(
    r"^(请|帮我|给我|麻烦|可以|能不能|你能不能)?"
    r"(画|绘制|生成|做|设计|创作|制作)"
    r"(一张|一幅|一只|一个|一条|一辆|一朵|一棵|一下|个|张|幅|只|条)?"
    r".{1,80}$",
    re.IGNORECASE,
)
_IMAGE_EDIT_RE = re.compile(
    r"(根据|参考|基于|按|照着).{0,10}(这张图|这图|图片|照片|上图|刚才那张|上一张)"
    r"|把.{0,20}(图|图片|照片).{0,20}(改成|换成|变成|修改|调整|优化|重画|二创)"
    r"|给.{0,12}(图|图片|照片).{0,12}(换|改|加|去掉|重画|扩图|补全)",
    re.IGNORECASE,
)
_IMAGE_ANALYZE_RE = re.compile(
    r"(图里|图片里|照片里|这张图|这图|上图|刚才那张|上一张).{0,16}(有什么|是什么|是谁|在哪|内容|意思|问题|好不好|怎么样|分析|识别|描述|看看|说说|评价)"
    r"|((识别|分析|看看|描述|评价|解释).{0,16}(这张图|这图|图片|照片))",
    re.IGNORECASE,
)
_IMAGE_REFERENCE_RE = re.compile(
    r"(这张图|这图|图片|照片|上图|刚才那张|上一张|图里|图片里|照片里|参考|根据|基于|照着)",
    re.IGNORECASE,
)
_IMAGE_IMPLICIT_EDIT_RE = re.compile(
    r"(换|改|变成|做成|生成|画成|重画|二创|场景|背景|风格|氛围|姿势|构图|高级|精致|清晰|修复|去掉|加上|添加|扩图|补全)",
    re.IGNORECASE,
)
_IMAGE_DISCUSSION_RE = re.compile(
    r"(怎么|如何|为什么|教程|步骤|方法|接口|api|API|代码|报错|失败|问题|原理|区别|能不能|可以吗|会不会|是什么|什么意思).{0,24}"
    r"(画|绘制|生成|做|设计|创作|制作|图|图片|图像|海报|头像|插画|壁纸|封面|logo|标志)"
    r"|(画图|绘图|生图|图片生成|图像生成|gpt-image|logo|头像).{0,24}"
    r"(怎么|如何|为什么|教程|步骤|方法|接口|api|API|代码|报错|失败|问题|原理|区别|能不能|可以吗|会不会|是什么|什么意思)",
    re.IGNORECASE,
)
_CHAT_HINT_RE = re.compile(
    r"(你好|在吗|早上好|晚上好|谢谢|帮我|翻译|总结|润色|改写|解释|分析|推荐|写个|写一段|问一下|请教|告诉我)",
    re.IGNORECASE,
)
_NOTICE_CANDIDATE_RE = re.compile(
    r"(查询|查一下|帮我查|搜索|检索|找一下|对比|比较|比价|整理|汇总|归纳|分析|长文|大量|方案|计划|规划|攻略|报告|表格|预算|复杂计算|多步骤|航班|车次|订单|进度|资料)",
    re.IGNORECASE,
)
_SEARCH_QUERY_RE = re.compile(
    r"(今天|明天|后天|現在|现在|最新|实时|剛剛|刚刚|新闻|热搜|天气|气温|机票|航班|车票|火车票|高铁|酒店|价格|汇率|股票|基金|赛事|赛程|比分|政策|公告|开放时间|地址|电话|查一下|帮我查|搜索|检索)",
    re.IGNORECASE,
)
_RESOLUTION_2K_RE = re.compile(r"(2k|2048|2K)", re.IGNORECASE)
_RESOLUTION_4K_RE = re.compile(r"(4k|3840|4096|4K|超清|高清)", re.IGNORECASE)
_SIZE_1_1_RE = re.compile(r"(1\s*[:：比]\s*1|方图|正方形|方形)", re.IGNORECASE)
_SIZE_16_9_RE = re.compile(r"(16\s*[:：比]\s*9|横版|横屏|宽屏|电影感|封面图|电脑壁纸)", re.IGNORECASE)
_SIZE_9_16_RE = re.compile(r"(9\s*[:：比]\s*16|竖版|竖屏|手机壁纸|小红书|抖音|海报竖版)", re.IGNORECASE)
_SIZE_4_3_RE = re.compile(r"(4\s*[:：比]\s*3|4:3)", re.IGNORECASE)
_SIZE_3_4_RE = re.compile(r"(3\s*[:：比]\s*4|3:4)", re.IGNORECASE)
_CLEAR_HISTORY_COMMANDS = {
    "/清空记忆",
    "/清空上下文",
    "/忘记上下文",
    "/重置对话",
    "清空记忆",
    "清空上下文",
    "忘记上下文",
    "重置对话",
}
_IDENTITY_QUERY_RE = re.compile(
    r"^(我就要知道)?(你是谁|你是誰|你是什么|你是什麼|你是什么模型|你是什麼模型|你用的什么模型|你用的什麼模型|你是什么AI|你是什么ai|你是哪个模型|你是哪個模型|模型是什么|模型是什麼|你能做什么|你會做什麼|你会做什么|你有什么用|你能帮我什么|你能帮我做什么|你能幫我什麼|你能幫我做什麼|你可以做什么|你可以幹什麼|介绍一下你自己|介紹一下你自己)[？?！!\s。]*$",
    re.IGNORECASE,
)
_POLLUTED_HISTORY_RE = re.compile(
    r"(\[\d{4}-\d{2}-\d{2}.*?\]\[.*?\]\[.*?\]\[[A-Z]\])"
    r"|(\[群AI(桥接|聚合)\])"
    r"|(INFO:\s+\d+\.\d+\.\d+\.\d+:\d+\s+-\s+\"(GET|POST|PUT|DELETE)\s+/)"
    r"|(Traceback \(most recent call last\)|Exception:|HTTPException|Bad Gateway)"
    r"|(send-message start|handle-msg talker=|handle-text isGroup=|native response length=)"
    r"|(<turn_aborted>|<environment_context>|</INSTRUCTIONS>|AGENTS\.md)"
    r"|(\"role\"\s*:\s*\"assistant\"|\"content\"\s*:|```)",
    re.IGNORECASE | re.DOTALL,
)
_ASSISTANT_STYLE_INPUT_RE = re.compile(
    r"^(收到|好的|当然|可以|没问题|明白|哈哈|嗯)[！!，,].{0,120}(你负责|我负责|咱俩|配合|我可以|我会|我能)"
    r"|^你(问|问我|刚问).{0,50}我(可以|会|能)",
    re.IGNORECASE | re.DOTALL,
)
_ASSISTANT_IDENTITY_LEAK_RE = re.compile(
    r"(Claude\s*Code|Codex|Anthropic|OpenAI|命令行\s*AI|编程助手|终端命令|创建\s*PR|运行终端|读写代码文件)"
    r"|我的工作是帮你写代码|只要是能在终端|我是个会写代码的",
    re.IGNORECASE,
)


def _strip_known_prefixes(text: str) -> str:
    value = str(text or "").strip()
    prefixes = _DRAW_PREFIXES + _CHAT_PREFIXES
    for prefix in prefixes:
        if value.startswith(prefix):
            return value[len(prefix):].strip()
    return value


def _has_prefix(text: str, prefixes: tuple[str, ...]) -> bool:
    value = str(text or "").strip()
    return any(value.startswith(prefix) for prefix in prefixes)


def _detect_resolution(text: str) -> str:
    value = str(text or "")
    if _RESOLUTION_4K_RE.search(value):
        return "4k"
    if _RESOLUTION_2K_RE.search(value):
        return "2k"
    return ""


def _detect_size(text: str) -> str:
    value = str(text or "")
    if _SIZE_16_9_RE.search(value):
        return "16:9"
    if _SIZE_9_16_RE.search(value):
        return "9:16"
    if _SIZE_4_3_RE.search(value):
        return "4:3"
    if _SIZE_3_4_RE.search(value):
        return "3:4"
    if _SIZE_1_1_RE.search(value):
        return "1:1"
    return ""


def _rule_route(text: str, has_recent_image: bool) -> dict[str, object]:
    raw = str(text or "").strip()
    cleaned = _strip_known_prefixes(raw)
    resolution = _detect_resolution(raw)
    size = _detect_size(raw)

    if _has_prefix(raw, _DRAW_PREFIXES):
        return {"matched": True, "action": "draw", "prompt": cleaned or raw, "use_image": bool(_IMAGE_EDIT_RE.search(raw)), "resolution": resolution, "size": size}

    if _has_prefix(raw, _CHAT_PREFIXES):
        return {"matched": True, "action": "chat", "prompt": cleaned or raw, "use_image": bool(_IMAGE_ANALYZE_RE.search(raw)), "resolution": resolution, "size": size}

    if _IMAGE_DISCUSSION_RE.search(raw):
        return {"matched": True, "action": "chat", "prompt": cleaned or raw, "use_image": False, "resolution": "", "size": ""}

    if has_recent_image and _IMAGE_IMPLICIT_EDIT_RE.search(raw):
        return {"matched": True, "action": "draw", "prompt": cleaned or raw, "use_image": True, "resolution": resolution, "size": size}

    if _IMAGE_EDIT_RE.search(raw):
        return {"matched": True, "action": "draw", "prompt": cleaned or raw, "use_image": True, "resolution": resolution, "size": size}

    if _IMAGE_ANALYZE_RE.search(raw):
        return {"matched": True, "action": "chat", "prompt": cleaned or raw, "use_image": True, "resolution": "", "size": ""}

    if _DRAW_RE.search(raw):
        return {"matched": True, "action": "draw", "prompt": cleaned or raw, "use_image": False, "resolution": resolution, "size": size}

    if _SIMPLE_DRAW_RE.search(raw):
        return {"matched": True, "action": "draw", "prompt": cleaned or raw, "use_image": False, "resolution": resolution, "size": size}

    if _CHAT_HINT_RE.search(raw):
        return {"matched": True, "action": "chat", "prompt": cleaned or raw, "use_image": False, "resolution": "", "size": ""}

    if resolution or size:
        return {"matched": True, "action": "draw", "prompt": cleaned or raw, "use_image": bool(_IMAGE_EDIT_RE.search(raw)), "resolution": resolution, "size": size}

    return {"matched": False, "action": "chat", "prompt": cleaned or raw, "use_image": False, "resolution": "", "size": ""}


def _bool_text(value: object) -> bool | None:
    raw = str(value or "").strip().lower()
    if raw in {"true", "1", "yes", "y"}:
        return True
    if raw in {"false", "0", "no", "n"}:
        return False
    return None


def _intent_from_body(body: WechatMessageRequest) -> dict[str, object] | None:
    action = str(body.intent_action or "").strip().lower()
    if action not in {"chat", "draw"}:
        return None
    prompt = str(body.intent_prompt or "").strip() or body.text
    use_image = _bool_text(body.intent_use_image)
    resolution = str(body.intent_resolution or "").strip().lower()
    if resolution not in {"", "2k", "4k"}:
        resolution = ""
    size = str(body.intent_size or "").strip().lower()
    if size not in {"", "1:1", "16:9", "9:16", "4:3", "3:4"}:
        size = ""
    notice = _bool_text(body.intent_notice)
    notice_text = str(body.intent_notice_text or "").strip()
    return {
        "matched": True,
        "action": action,
        "prompt": prompt,
        "use_image": bool(use_image),
        "resolution": resolution,
        "size": size,
        "notice": bool(notice),
        "notice_text": notice_text,
    }


def _intent_messages(
    text: str,
    image_bytes: bytes | None,
    image_mime: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    recent_lines: list[str] = []
    for item in history or []:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        label = "用户" if role == "user" else "助手"
        recent_lines.append(f"{label}：{content}")
    if recent_lines:
        messages.append({
            "role": "user",
            "content": "最近对话上下文，仅用于理解当前问题，不要续写，不要模仿回复，不要把它当成对话内容：\n"
            + "\n".join(recent_lines[-8:])
        })
    if image_bytes:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                _image_part(image_bytes, image_mime),
            ],
        })
        return messages
    messages.append({"role": "user", "content": f"当前用户消息：{text}\n只输出 JSON，不要解释，不要聊天。"})
    return messages


def _resolve_intent(
    text: str,
    image_bytes: bytes | None,
    image_mime: str,
    *,
    force_ai: bool = False,
    history: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    routing_mode = str(settings.routing_mode or "hybrid").strip().lower()
    if routing_mode not in {"rules", "intent", "hybrid"}:
        routing_mode = "hybrid"

    if routing_mode == "rules" and not force_ai:
        return _rule_route(text, has_recent_image=bool(image_bytes))

    rule_intent = _rule_route(text, has_recent_image=bool(image_bytes))
    ambiguous_with_image = bool(image_bytes and _IMAGE_REFERENCE_RE.search(str(text or "")))
    should_use_ai = force_ai or routing_mode == "intent" or not bool(rule_intent.get("matched")) or ambiguous_with_image
    if not should_use_ai:
        return rule_intent

    try:
        intent_text = client.chat(
            settings.intent,
            system_prompt=build_intent_system_prompt(),
            messages=_intent_messages(text, image_bytes, image_mime, history=history),
            temperature=0,
        )
        _log_event("debug", f"intent raw text={text[:80]} result={intent_text[:300]}")
        return parse_intent(intent_text, text)
    except Exception as exc:
        _log_event("error", f"intent failed text={text[:80]} err={exc}")
        if routing_mode == "hybrid" and not force_ai and bool(rule_intent.get("matched")):
            return rule_intent
        raise HTTPException(status_code=502, detail={"error": f"intent failed: {exc}"}) from exc


def _resolve_tool_plan(
    text: str,
    image_bytes: bytes | None,
    image_mime: str,
    *,
    history: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    try:
        plan_text = client.chat(
            settings.intent,
            system_prompt=build_tool_planner_prompt(),
            messages=_intent_messages(text, image_bytes, image_mime, history=history),
            temperature=0,
        )
        _log_event("debug", f"tool plan raw text={text[:80]} plan={plan_text[:300]}")
        plan = parse_tool_plan(plan_text, text)
        _log_event(
            "debug",
            f"tool plan parsed tool={plan.get('tool')} prompt={str(plan.get('prompt') or '')[:80]} notice={plan.get('notice')}"
        )
        return plan
    except Exception as exc:
        _log_event("error", f"tool planning failed text={text[:80]} err={exc}")
        raise HTTPException(status_code=502, detail={"error": f"tool planning failed: {exc}"}) from exc


def _tool_plan_to_intent(plan: dict[str, object], fallback_prompt: str) -> dict[str, object]:
    tool = str(plan.get("tool") or "chat")
    args = plan.get("args") if isinstance(plan.get("args"), dict) else {}
    prompt = str(args.get("prompt") or args.get("query") or plan.get("prompt") or fallback_prompt).strip() or fallback_prompt
    resolution = str(args.get("resolution") or "").strip().lower()
    if resolution not in {"", "2k", "4k"}:
        resolution = ""
    size = str(args.get("size") or "").strip().lower()
    if size not in {"", "1:1", "16:9", "9:16", "4:3", "3:4"}:
        size = ""
    if tool == "image_generate":
        return {"matched": True, "action": "draw", "prompt": prompt, "use_image": False, "resolution": resolution, "size": size, "notice": False}
    if tool == "image_edit":
        return {"matched": True, "action": "draw", "prompt": prompt, "use_image": True, "resolution": resolution, "size": size, "notice": False}
    if tool == "image_analyze":
        return {"matched": True, "action": "chat", "prompt": prompt, "use_image": True, "resolution": "", "size": "", "notice": True}
    return {"matched": True, "action": "chat", "prompt": prompt, "use_image": False, "resolution": "", "size": "", "notice": bool(plan.get("notice"))}


def _safe_calculate(expression: str) -> str:
    expr = str(expression or "").strip()
    if not expr:
        raise ProviderError("计算表达式为空")
    expr = expr.replace("÷", "/").replace("×", "*").replace("－", "-").replace("＋", "+")
    expr = re.sub(r"(?<=\d)\s*%\s*", "/100", expr)
    tree = ast.parse(expr, mode="eval")
    allowed_binops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv,
    }
    allowed_unary = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    def _eval(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return Decimal(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_binops:
            left = _eval(node.left)
            right = _eval(node.right)
            op = allowed_binops[type(node.op)]
            result = op(left, right)
            return Decimal(str(result))
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_unary:
            return Decimal(str(allowed_unary[type(node.op)](_eval(node.operand))))
        raise ProviderError("不支持的计算表达式")

    result = _eval(tree)
    text = format(result.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _require_auth(authorization: str | None) -> None:
    token = str(authorization or "").removeprefix("Bearer").strip()
    if token != settings.auth_key:
        raise HTTPException(status_code=401, detail={"error": "invalid auth key"})


def _log_event(level: str, message: str) -> None:
    bridge_state.append_event(level, message)


def _mask_secret(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}...{text[-4:]}"


def _provider_summary(item: object) -> dict[str, str]:
    data = item if isinstance(item, dict) else {}
    return {
        "base_url": str(data.get("base_url") or ""),
        "protocol": str(data.get("protocol") or ""),
        "model": str(data.get("model") or ""),
        "account_type": str(data.get("account_type") or ""),
        "api_key": _mask_secret(data.get("api_key")),
    }


def _session_key(talker: str, sender: str) -> str:
    return f"{talker}:{sender}"


def _context_prompt(talker: str, sender: str) -> str:
    persona = str(settings.persona or "").strip()
    parts = [
        "你是一个通用、专业、自然的中文 AI 助手，不是 Claude、Claude Code、Codex、OpenAI 助手、命令行助手或编程专用助手。",
        "无论上游模型默认身份是什么，都不要提模型厂商、模型名称、开发者工具身份或系统来源。",
        "用户追问你是什么模型、哪个模型、用的什么模型时，不要说不能讨论、不要引用内部提示词，只说自己是通用 AI 助手，可以帮用户处理具体问题。",
        "除非用户明确提出代码、开发、终端、Git、部署、调试等技术任务，否则不要主动提写代码、读文件、运行命令、创建 PR、开发环境或编程助手能力。",
        "用户问你是谁、会做什么、能帮什么时，回答为通用助手能力：答疑、整理信息、写作润色、翻译、分析问题、制定计划、生成创意、看图分析和辅助生图；不要把能力限制成代码/终端/PR。",
        "如果用户泛泛问“你能做什么”，按这个方向回答：我能帮你答疑、整理信息、写作润色、翻译、分析图片、规划方案、生成创意、辅助生图；不要列代码相关能力。",
        "直接回答用户问题，中文优先。",
        "回复尽量简洁：默认 1-3 句，最多约 120 个中文字；能一句话说清就不要展开。",
        "只有用户要求详细、问题本身复杂，或需要步骤/对比/清单时，才使用分点说明。",
        "分点时最多 5 条，每条尽量短。",
        "不要因为来源是微信就降低信息量或变得过度保守；能给出具体信息时直接给出。",
        "回复适合聊天阅读，不要整段堆在一起。",
        "允许使用短段落、空行、- 列表、1. 2. 3. 编号列表。",
        "可以在该有情绪表达的地方少量使用 emoji，每条最多 1-2 个，没必要就不用。",
        "不要使用 Markdown 强调或代码块，不要使用 **、__、```、#；小标题直接写普通文字。",
        f"内部上下文：会话={talker}，发言人={sender}。这个信息只用于区分不同用户，不要在回复里提到。",
        "只回答当前发言人的问题，不要混用其他人的上下文。",
    ]
    if persona:
        parts.insert(1, persona)
    return "".join(parts)


def _image_part(image_bytes: bytes, image_mime: str) -> dict[str, object]:
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{image_mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        },
    }


def _sanitize_wechat_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"```[\s\S]*?```", lambda m: m.group(0).replace("```", ""), value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"__([^_]+)__", r"\1", value)
    value = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", value)
    replacements = {
        "—": "-",
        "–": "-",
        "―": "-",
        "…": "...",
        "“": "\"",
        "”": "\"",
        "‘": "'",
        "’": "'",
        "•": "-",
        "·": ".",
        "\u00A0": " ",
        "\u2002": " ",
        "\u2003": " ",
        "\u2004": " ",
        "\u2005": " ",
        "\u2006": " ",
        "\u2007": " ",
        "\u2008": " ",
        "\u2009": " ",
        "\u200A": " ",
        "\u200B": "",
        "\u2028": "\n",
        "\u2029": "\n",
        "\uFEFF": "",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    out: list[str] = []
    emoji_count = 0
    for ch in value:
        code = ord(ch)
        if code in {9, 10, 13}:
            out.append(ch)
            continue
        if 0x1F300 <= code <= 0x1FAFF:
            if emoji_count < 2:
                out.append(ch)
                emoji_count += 1
            continue
        if 32 <= code <= 0xD7FF:
            out.append(ch)
            continue
        if 0xE000 <= code <= 0xFFFD:
            out.append(ch)
    cleaned = "".join(out)
    # Collapse noisy repeated whitespace without destroying line breaks.
    cleaned = "\n".join(" ".join(line.split()) for line in cleaned.splitlines())
    cleaned = cleaned.strip()
    if not cleaned:
        return "..."
    if len(cleaned) > 1500:
        return cleaned[:1500].rstrip() + "..."
    return cleaned


def _is_clear_history_command(text: str) -> bool:
    return str(text or "").strip() in _CLEAR_HISTORY_COMMANDS


def _is_identity_query(text: str) -> bool:
    return bool(_IDENTITY_QUERY_RE.search(str(text or "").strip()))


def _identity_reply() -> str:
    return (
        "我是一个通用 AI 助手。\n"
        "- 答疑、整理信息\n"
        "- 写作润色、翻译\n"
        "- 分析问题、制定计划\n"
        "- 看图分析、辅助生图\n"
        "你直接说需求就行。"
    )


def _should_store_user_history(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if len(value) > settings.history_user_max_chars:
        return False
    if value.count("\n") >= 6:
        return False
    if _POLLUTED_HISTORY_RE.search(value):
        return False
    if _ASSISTANT_STYLE_INPUT_RE.search(value):
        return False
    return True


def _history_text(text: str, max_chars: int) -> str:
    value = _sanitize_wechat_text(text)
    if len(value) > max_chars:
        return value[:max_chars].rstrip() + "..."
    return value


def _needs_search(text: str) -> bool:
    return False


def _search_query(text: str) -> str:
    value = str(text or "").strip()
    compact = re.sub(r"\s+", "", value)
    if ("昆明" in compact and ("香格里拉" in compact or "迪庆" in compact) and ("机票" in compact or "航班" in compact)):
        return f"{value} KMG DIG 昆明 迪庆 香格里拉 航班 机票"
    return value


def _format_search_results(results: list[dict[str, str]], limit: int | None = None) -> str:
    lines: list[str] = []
    max_items = limit or len(results)
    for idx, item in enumerate(results[:max_items], start=1):
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        url = str(item.get("url") or "").strip()
        line = f"{idx}. {title}"
        if content:
            line += f"\n摘要：{content[:260]}"
        if url:
            line += f"\n来源：{url}"
        lines.append(line)
    return "\n\n".join(lines)


def _review_search_results(query: str, results: list[dict[str, str]]) -> list[dict[str, str]]:
    if not results:
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    review_prompt = (
        "你是搜索结果审查器，只输出 JSON。"
        "根据用户问题、当前日期和搜索结果，筛出真正能回答问题的结果。"
        "你必须动态理解今天、明天、后天、大后天、下周、具体日期，不准写死日期。"
        "只保留地点、日期、任务类型匹配的结果；天气问题要匹配地点和日期；机票/航班问题要匹配出发地、目的地、日期或航线。"
        "入口页、广告页、酒店页、旅游团页面、旧新闻、地点不匹配、日期不匹配的结果要丢弃。"
        '输出格式：{"valid_indexes":[1,2],"reason":"简短理由"}。'
    )
    content = (
        f"当前日期：{today}\n"
        f"用户问题：{query}\n\n"
        f"搜索结果：\n{_format_search_results(results)}"
    )
    try:
        text = client.chat(
            settings.intent,
            system_prompt=review_prompt,
            messages=[{"role": "user", "content": content}],
        )
        data = json.loads(text)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    indexes = data.get("valid_indexes")
    if not isinstance(indexes, list):
        return []
    valid: list[dict[str, str]] = []
    for raw in indexes:
        try:
            index = int(raw)
        except Exception:
            continue
        if 1 <= index <= len(results):
            valid.append(results[index - 1])
        if len(valid) >= settings.search_max_results:
            break
    return valid


def _search_context(query: str) -> str:
    try:
        results = client.search(_search_query(query))
    except Exception:
        return ""
    if not results:
        return ""
    reviewed = _review_search_results(query, results)
    lines = ["经审查后的联网搜索结果："]
    if reviewed:
        lines.append(_format_search_results(reviewed, settings.search_max_results))
    else:
        lines.append("没有找到能可靠匹配用户问题、日期、地点和任务类型的搜索结果。")
    lines.append("请只基于以上审查后的结果回答；结果为空或不足时直接说明没查到可靠实时结果，不要使用未经审查的搜索结果，不要编造实时价格、余票、日期或天气。")
    return "\n\n".join(lines)


def _chat_system_prompt(talker: str, sender: str, search_context: str = "") -> str:
    prompt = _context_prompt(talker, sender)
    prompt += (
        "\n如果用户的说法和工具结果冲突，必须以工具结果为准，直接纠正，不要为了迎合用户而改错。"
        "如果你前面算错、记错或说错了，要直接承认并给出正确答案，不要硬撑，也不要反过来顺着错误前提继续说。"
        "不要无条件说‘你说得对’。"
    )
    if search_context:
        if "实时天气工具结果：" in search_context:
            prompt = (
                f"{prompt}\n"
                "你已经拿到了天气工具结果，必须直接基于工具结果作答。"
                "目标日期字段就是用户要问的日期，不要自己重新计算今天、明天或后天。"
                "不要说没有天气数据，不要建议用户去天气网站或天气 APP。"
                "回复要简洁，直接给地点、日期、天气、温度、降雨概率和一句提醒。"
                f"\n\n{search_context}"
            )
        else:
            prompt = (
                f"{prompt}\n"
                "你已经拿到了实时联网搜索结果，必须基于这些结果作答。"
                "不要再说无法实时查询，也不要把用户打发去其他平台。"
                "如果结果足够，就直接给出简洁结论；如果结果不足，就明确说目前搜索结果不够，不要编造。"
                f"\n\n{search_context}"
            )
    return prompt


def _usable_history(history: list[dict[str, object]]) -> list[dict[str, str]]:
    usable: list[dict[str, str]] = []
    keep_next_assistant = False
    for item in history:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if role == "user":
            keep_next_assistant = _should_store_user_history(content)
            if keep_next_assistant:
                usable.append({"role": "user", "content": _history_text(content, settings.history_user_max_chars)})
            continue
        if role == "assistant":
            if keep_next_assistant and not _ASSISTANT_IDENTITY_LEAK_RE.search(content):
                usable.append({"role": "assistant", "content": _history_text(content, settings.history_assistant_max_chars)})
            keep_next_assistant = False
    return usable[-settings.history_limit:]


@router.get("/health")
def health() -> dict[str, object]:
    return {"ok": True}


@router.get("/api/ui/status")
def ui_status(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_auth(authorization)
    config_data = read_config_file()
    sessions = bridge_state.data.get("sessions") if isinstance(bridge_state.data, dict) else {}
    images = bridge_state.data.get("images") if isinstance(bridge_state.data, dict) else {}
    session_items = []
    if isinstance(sessions, dict):
        for key, value in sessions.items():
            item = value if isinstance(value, dict) else {}
            history = item.get("history") if isinstance(item.get("history"), list) else []
            session_items.append({
                "key": key,
                "history_count": len(history),
                "updated_at": int(item.get("updated_at") or 0),
            })
    session_items.sort(key=lambda item: int(item["updated_at"]), reverse=True)
    valid_images = 0
    if isinstance(images, dict):
        now = int(time.time())
        for item in images.values():
            if isinstance(item, dict) and now - int(item.get("updated_at") or 0) <= settings.image_ttl_seconds:
                valid_images += 1
    return {
        "ok": True,
        "service": "WxLinkAI",
        "routing_mode": str(config_data.get("routing_mode") or settings.routing_mode),
        "visual_chat_provider": str(config_data.get("visual_chat_provider") or settings.visual_chat_provider),
        "history_limit": int(config_data.get("history_limit") or settings.history_limit),
        "image_ttl_seconds": int(config_data.get("image_ttl_seconds") or settings.image_ttl_seconds),
        "sessions": len(sessions) if isinstance(sessions, dict) else 0,
        "images": valid_images,
        "recent_sessions": session_items[:8],
        "providers": {
            "chat": _provider_summary(config_data.get("chat")),
            "intent": _provider_summary(config_data.get("intent")),
            "image": _provider_summary(config_data.get("image")),
        },
        "search": config_data.get("search") if isinstance(config_data.get("search"), dict) else {},
    }


@router.get("/api/ui/logs")
def ui_logs(after: int = 0, limit: int = 200, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_auth(authorization)
    return {
        "ok": True,
        "events": bridge_state.get_events(after_seq=max(0, int(after)), limit=max(1, min(200, int(limit)))),
    }


@router.get("/api/ui/config")
def ui_config(authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_auth(authorization)
    return {"ok": True, "config": read_config_file()}


@router.post("/api/ui/config")
def ui_save_config(payload: dict[str, object], authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_auth(authorization)
    data = payload.get("config") if isinstance(payload.get("config"), dict) else payload
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail={"error": "config must be object"})
    save_config_file(data)
    reload_settings()
    _log_event("info", "配置已保存并热加载")
    return {"ok": True, "message": "配置已保存并热加载，无需重启。"}


@router.post("/wechat/cache-image")
def cache_image(body: WechatImageCacheRequest, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_auth(authorization)
    session_key = _session_key(body.talker, body.sender)
    path = bridge_state.remember_image(session_key, body.image_b64, body.image_mime)
    _log_event("info", f"cache-image {session_key} -> {path}")
    return {"ok": True, "session_key": session_key, "path": path}


@router.post("/wechat/intent")
def resolve_intent(body: WechatIntentRequest, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _require_auth(authorization)
    _log_event("debug", f"intent request {body.talker}:{body.sender} text={body.text}")
    if _is_identity_query(body.text):
        return {
            "action": "chat",
            "prompt": body.text,
            "use_image": "false",
            "resolution": "",
            "size": "",
            "notice": "false",
            "notice_text": "",
            "has_image": "false",
        }
    session_key = _session_key(body.talker, body.sender)
    history = _usable_history(bridge_state.get_history(session_key))
    recent_image = bridge_state.get_recent_image(session_key)
    image_bytes = recent_image[0] if recent_image else None
    image_mime = recent_image[1] if recent_image else "image/png"
    try:
        plan = _resolve_tool_plan(body.text, image_bytes, image_mime, history=history)
        plan = enforce_tool_plan(plan, body.text)
        intent = _tool_plan_to_intent(plan, body.text)
    except HTTPException:
        plan = {"tool": "chat"}
        intent = {
            "action": "chat",
            "prompt": body.text,
            "use_image": False,
            "resolution": "",
            "size": "",
            "notice": False,
            "notice_text": "",
        }
    notice = bool(intent.get("notice"))
    if str(plan.get("tool") or "") in {"weather", "web_search"}:
        notice = False
    return {
        "action": str(intent.get("action") or "chat"),
        "prompt": str(intent.get("prompt") or body.text),
        "use_image": "true" if bool(intent.get("use_image")) else "false",
        "resolution": str(intent.get("resolution") or ""),
        "size": str(intent.get("size") or ""),
        "notice": "true" if notice else "false",
        "notice_text": CHAT_NOTICE_TEXT if notice else "",
        "has_image": "true" if bool(image_bytes) else "false",
    }


def _wants_pipe(body: WechatMessageRequest) -> bool:
    return str(body.response_format or "").strip().lower() == "pipe"


def _wants_plain(body: WechatMessageRequest) -> bool:
    return str(body.response_format or "").strip().lower() == "plain"


def _plain_response(resp: WechatBridgeResponse) -> Response:
    return Response(str(resp.reply_text or ""), media_type="text/plain; charset=utf-8")


def _pipe_response(resp: WechatBridgeResponse) -> Response:
    text_b64 = base64.b64encode(str(resp.reply_text or "").encode("utf-8")).decode("ascii")
    lines = [
        f"MODE={resp.mode}",
        f"TASK_ID={resp.task_id}",
        f"USED_IMAGE={'true' if resp.used_image else 'false'}",
        f"TEXT_B64={text_b64}",
    ]
    for image in resp.images_b64:
        if image:
            lines.append(f"IMAGE_B64={image}")
    return Response("\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")


def _bridge_response(resp: WechatBridgeResponse, body: WechatMessageRequest) -> WechatBridgeResponse | Response:
    if _wants_plain(body):
        return _plain_response(resp)
    if _wants_pipe(body):
        return _pipe_response(resp)
    return resp


def _draw_failed_response(task_id: str, exc: Exception, body: WechatMessageRequest) -> WechatBridgeResponse | Response:
    message = str(exc or "").strip() or "上游没有返回具体原因"
    text = f"生图失败 [任务ID: {task_id}]\n原因：{message}"
    return _bridge_response(WechatBridgeResponse(
        mode="error",
        reply_text=_sanitize_wechat_text(text),
        session_key=_session_key(body.talker, body.sender),
        used_image=False,
        task_id=task_id,
    ), body)


@router.post("/wechat/message", response_model=None)
def handle_message(body: WechatMessageRequest, authorization: str | None = Header(default=None)) -> WechatBridgeResponse | Response:
    _require_auth(authorization)
    session_key = _session_key(body.talker, body.sender)
    _log_event("debug", f"message {session_key} text={body.text[:120]}")

    if _is_clear_history_command(body.text):
        bridge_state.clear_history(session_key)
        _log_event("info", f"history cleared {session_key}")
        return _bridge_response(WechatBridgeResponse(
            mode="chat",
            reply_text=_sanitize_wechat_text("已清空你的对话记忆。"),
            session_key=session_key,
            used_image=False,
        ), body)

    if body.image_b64:
        bridge_state.remember_image(session_key, body.image_b64, body.image_mime)

    recent_image = bridge_state.get_recent_image(session_key)
    image_bytes = recent_image[0] if recent_image else None
    image_mime = recent_image[1] if recent_image else "image/png"
    history = _usable_history(bridge_state.get_history(session_key))

    try:
        tool_plan = _resolve_tool_plan(body.text, image_bytes, image_mime, history=history)
    except HTTPException:
        tool_plan = {"tool": "chat", "args": {"prompt": body.text}, "prompt": body.text, "notice": False}
    tool_plan = enforce_tool_plan(tool_plan, body.text)
    intent = _intent_from_body(body) or _tool_plan_to_intent(tool_plan, body.text)

    prompt = str(intent["prompt"] or body.text).strip() or body.text
    resolution = str(intent["resolution"] or "").strip()
    size = str(intent.get("size") or "").strip()
    use_image = bool(intent["use_image"])

    if use_image and not image_bytes:
        _log_event("warn", f"draw missing image {session_key}")
        return _bridge_response(WechatBridgeResponse(
            mode="error",
            reply_text=_sanitize_wechat_text("我没看到你最近发的图片，先发图再 @ 我问。"),
            session_key=session_key,
            used_image=False,
        ), body)

    if intent["action"] == "chat" and not use_image and _is_identity_query(prompt):
        reply = _identity_reply()
        if _should_store_user_history(prompt):
            bridge_state.append_history(session_key, "user", _history_text(prompt, settings.history_user_max_chars))
            bridge_state.append_history(session_key, "assistant", _history_text(reply, settings.history_assistant_max_chars))
        return _bridge_response(WechatBridgeResponse(
            mode="chat",
            reply_text=_sanitize_wechat_text(reply),
            session_key=session_key,
            used_image=False,
        ), body)

    if intent["action"] == "draw":
        task_id = str(body.client_task_id or "").strip() or uuid.uuid4().hex[:8]
        task_notice = "" if body.notice_sent else f"已开始生图任务 [任务ID: {task_id}]"
        _log_event("info", f"draw start {session_key} task={task_id} prompt={prompt}")
        if use_image:
            try:
                images = client.edit_image(prompt, image_bytes, image_mime, resolution, size)
            except Exception as exc:
                _log_event("error", f"draw failed {session_key} task={task_id} err={exc}")
                return _draw_failed_response(task_id, exc, body)
            return _bridge_response(WechatBridgeResponse(
                mode="draw",
                reply_text=_sanitize_wechat_text(task_notice) if task_notice else "",
                images_b64=images,
                session_key=session_key,
                used_image=True,
                task_id=task_id,
            ), body)
        try:
            images = client.generate_image(prompt, resolution, size)
        except Exception as exc:
            _log_event("error", f"draw failed {session_key} task={task_id} err={exc}")
            return _draw_failed_response(task_id, exc, body)
        return _bridge_response(WechatBridgeResponse(
            mode="draw",
            reply_text=_sanitize_wechat_text(task_notice) if task_notice else "",
            images_b64=images,
            session_key=session_key,
            used_image=False,
            task_id=task_id,
        ), body)

    try:
        if use_image and image_bytes:
            reply = client.visual_chat(prompt, image_bytes, image_mime)
        else:
            history = _usable_history(bridge_state.get_history(session_key))
            messages: list[dict[str, object]] = list(history)
            tool_name = str(tool_plan.get("tool") or "")
            tool_args = tool_plan.get("args") if isinstance(tool_plan.get("args"), dict) else {}
            if tool_name == "weather":
                location = str(tool_args.get("location") or "").strip()
                if not location:
                    reply = "你要查哪个城市的天气？地点给我一个，不然我只能干瞪眼。"
                    return _bridge_response(WechatBridgeResponse(
                        mode="chat",
                        reply_text=_sanitize_wechat_text(reply),
                        session_key=session_key,
                        used_image=False,
                    ), body)
                try:
                    search_context = weather_context_with_repair(body.text, tool_args)
                except ProviderError as exc:
                    reply = f"天气工具没查到可靠结果：{exc}"
                    return _bridge_response(WechatBridgeResponse(
                        mode="chat",
                        reply_text=_sanitize_wechat_text(reply),
                        session_key=session_key,
                        used_image=False,
                    ), body)
            elif tool_name == "calculator":
                expression = str(tool_args.get("expression") or prompt).strip()
                try:
                    calc_result = _safe_calculate(expression)
                except ProviderError as exc:
                    reply = f"计算失败：{exc}"
                    return _bridge_response(WechatBridgeResponse(
                        mode="chat",
                        reply_text=_sanitize_wechat_text(reply),
                        session_key=session_key,
                        used_image=False,
                    ), body)
                search_context = f"计算结果：{expression} = {calc_result}\n请直接基于这个计算结果回答，别重新心算。"
            elif tool_name == "web_search":
                search_query = str(tool_args.get("query") or prompt)
                search_context = _search_context(search_query)
            else:
                search_context = ""
            messages.append({"role": "user", "content": prompt})
            reply = client.chat(
                settings.chat,
                system_prompt=_chat_system_prompt(body.talker, body.sender, search_context),
                messages=messages,
                temperature=0.2,
            )
        _log_event("info", f"reply {session_key} mode=chat len={len(str(reply))}")
    except ProviderError as exc:
        _log_event("error", f"chat failed {session_key} err={exc}")
        raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
    except Exception as exc:
        _log_event("error", f"chat failed {session_key} err={exc}")
        raise HTTPException(status_code=502, detail={"error": f"chat failed: {exc}"}) from exc

    if _should_store_user_history(prompt):
        bridge_state.append_history(session_key, "user", _history_text(prompt, settings.history_user_max_chars))
        bridge_state.append_history(session_key, "assistant", _history_text(reply, settings.history_assistant_max_chars))
    return _bridge_response(WechatBridgeResponse(
        mode="chat",
        reply_text=_sanitize_wechat_text(reply),
        session_key=session_key,
        used_image=bool(use_image and image_bytes),
    ), body)
