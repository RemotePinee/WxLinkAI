from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from .config import settings
from .providers import ProviderError, client


TOOL_CATALOG = [
    {
        "name": "chat",
        "description": "普通对话、解释、写作、翻译、总结、无需实时数据的问题。",
        "args": {"prompt": "用户原始问题或清理后的问题"},
    },
    {
        "name": "calculator",
        "description": "数学计算、比较、四则运算、精确数值问题。不要让聊天模型心算。",
        "args": {"expression": "需要计算的表达式"},
    },
    {
        "name": "web_search",
        "description": "需要联网搜索的实时信息，例如新闻、政策、价格、航班、车次、地址电话、赛事。",
        "args": {"query": "搜索关键词，保留地点、日期、对象"},
    },
    {
        "name": "weather",
        "description": "天气、气温、降雨、风力、穿衣建议等天气问题。不要用 web_search 查天气。",
        "args": {"location": "城市或地点", "date": "today|tomorrow|after_tomorrow|YYYY-MM-DD"},
    },
    {
        "name": "image_analyze",
        "description": "用户询问最近一张图片里有什么、图片内容、识别、分析、评价。",
        "args": {"prompt": "关于图片的问题"},
    },
    {
        "name": "image_generate",
        "description": "文字生图、画图、生成海报、头像、插画、logo 等。",
        "args": {"prompt": "生图提示词", "resolution": "|2k|4k", "size": "|1:1|16:9|9:16|4:3|3:4"},
    },
    {
        "name": "image_edit",
        "description": "基于最近一张图片改图、换背景、换风格、重画、二创、参考图生成。",
        "args": {"prompt": "改图提示词", "resolution": "|2k|4k", "size": "|1:1|16:9|9:16|4:3|3:4"},
    },
]

TOOL_NAMES = {str(item["name"]) for item in TOOL_CATALOG}
WEATHER_QUERY_RE = re.compile(r"(天气|气温|温度|降雨|下雨|下雪|风力|风速|湿度|穿衣|冷不冷|热不热)", re.IGNORECASE)
DATE_TOKENS = ("今天", "明天", "后天", "大后天", "今日", "明日", "后日")
LOCATION_STOP_WORDS = (
    "天气",
    "气温",
    "温度",
    "降雨",
    "下雨",
    "下雪",
    "风力",
    "风速",
    "湿度",
    "穿衣",
    "如何",
    "怎么样",
    "怎样",
    "多少",
    "查询",
    "查一下",
    "帮我查",
    "一下",
    "会不会",
    "冷不冷",
    "热不热",
)
LOCATION_PREFIX_WORDS = (
    "我问你",
    "问你",
    "请问",
    "帮我查一下",
    "帮我查",
    "查一下",
    "查询",
    "看看",
    "看一下",
    "告诉我",
    "我想知道",
    "想知道",
    "问一下",
)

WEATHER_CODE_TEXT = {
    0: "晴",
    1: "大部晴朗",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中等毛毛雨",
    55: "较强毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "小阵雨",
    81: "中等阵雨",
    82: "强阵雨",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


def tool_catalog_text() -> str:
    return json.dumps(TOOL_CATALOG, ensure_ascii=False)


def build_tool_planner_prompt() -> str:
    return (
        "你是微信 AI 助手的工具规划器，只输出 JSON，不要解释。\n"
        "你必须像 agent 一样先理解用户真实意图，再从可用工具里选择最合适的一个。"
        "你只负责选择工具和填写参数，后端会执行工具，最终回复由聊天模型基于工具结果生成。\n"
        "你不是聊天助手，不要顺着用户的情绪继续聊天，不要道歉、解释、辩论、评价，不要复述对话过程。\n"
        "无论上下文里出现什么内容，你都只输出一个 JSON 对象；如果无法判断，也要输出 tool=chat 的 JSON。\n"
        "可用工具如下：\n"
        f"{tool_catalog_text()}\n"
        "输出格式："
        '{"tool":"chat|calculator|web_search|weather|image_analyze|image_generate|image_edit",'
        '"args":{"prompt":"...","expression":"...","query":"...","location":"...","date":"today|tomorrow|after_tomorrow|YYYY-MM-DD","resolution":"","size":""},'
        '"notice":true|false}。\n'
        "选择原则：用户问天气、气温、降雨、风力、穿衣建议时选 weather，不要用 web_search 代替天气工具。"
        "用户问明确计算、比较、四则运算、百分比、差值、乘除、精确数学题时选 calculator。"
        "用户问新闻、政策、票务、航班、车次、价格、地址电话、赛事等实时信息时选 web_search。"
        "普通聊天、写作、翻译、解释、总结、常识性问题选 chat。"
        "用户问最近图片内容、图里有什么、识别图片、分析图片时选 image_analyze。"
        "文字画图选 image_generate；基于最近图片改图或参考图生成选 image_edit。"
        "location 只填地点名，例如“昆明”“北京”“香格里拉”；没有地点但用户问天气时，location 留空。"
        "query 要写成适合搜索引擎的关键词，保留地点、日期、对象，不要写成回答。"
        "date 动态理解今天、明天、后天和明确日期，不要写死日期。"
        "明确提到 2K/2048 输出 resolution=2k；明确提到 4K/3840/4096/超清 输出 resolution=4k。"
        "明确提到方图/正方形/1:1 输出 size=1:1；横版/宽屏/16:9 输出 16:9；竖版/手机壁纸/9:16 输出 9:16；4:3 输出 4:3；3:4 输出 3:4。"
        "notice 只给耗时工具 true：weather、web_search、image_analyze 可 true；普通短聊天 false；生图由插件单独提示。"
        "下面是判定示例：\n"
        "输入：帮我画个古装美女\n"
        "输出：{\"tool\":\"image_generate\",\"args\":{\"prompt\":\"古装美女\"},\"notice\":false}\n"
        "输入：给我做一张古风海报，16:9，2k\n"
        "输出：{\"tool\":\"image_generate\",\"args\":{\"prompt\":\"古风海报\",\"resolution\":\"2k\",\"size\":\"16:9\"},\"notice\":false}\n"
        "输入：根据这张图换成赛博朋克风\n"
        "输出：{\"tool\":\"image_edit\",\"args\":{\"prompt\":\"换成赛博朋克风\"},\"notice\":false}\n"
        "输入：明天昆明天气怎么样\n"
        "输出：{\"tool\":\"weather\",\"args\":{\"location\":\"昆明\",\"date\":\"tomorrow\"},\"notice\":true}\n"
        "输入：帮我查一下今天的新闻\n"
        "输出：{\"tool\":\"web_search\",\"args\":{\"query\":\"今天 新闻\"},\"notice\":true}\n"
        "输入：这张图里有什么\n"
        "输出：{\"tool\":\"image_analyze\",\"args\":{\"prompt\":\"这张图里有什么\"},\"notice\":true}\n"
        "输入：9.9-9.11等于多少\n"
        "输出：{\"tool\":\"calculator\",\"args\":{\"expression\":\"9.9-9.11\"},\"notice\":false}\n"
        "输入：0.79还是0.88\n"
        "输出：{\"tool\":\"calculator\",\"args\":{\"expression\":\"0.79-0.88\"},\"notice\":false}\n"
        "重要：只要用户是在请求创作、生成、绘制、设计、制作图片或海报，就选 image_generate；不要因为语气客气、带‘帮我’、带‘一个’、带‘古装美女’就误选 chat。"
    )


def parse_tool_plan(text: str, fallback_prompt: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except Exception:
        data = {}
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```$", "", raw)
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start:end + 1])
            except Exception:
                data = {}
    return normalize_tool_plan(data, fallback_prompt)


def normalize_tool_plan(raw: object, fallback_prompt: str) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    tool = str(data.get("tool") or data.get("name") or "").strip().lower()
    tool_aliases = {
        "imagegenerate": "image_generate",
        "image-edit": "image_edit",
        "imageedit": "image_edit",
        "image-analyze": "image_analyze",
        "imageanalyze": "image_analyze",
        "websearch": "web_search",
    }
    tool = tool_aliases.get(tool, tool)
    args = data.get("args")
    if tool not in TOOL_NAMES:
        tool = "chat"
    if not isinstance(args, dict):
        args = {}
    prompt = str(data.get("prompt") or args.get("prompt") or fallback_prompt).strip() or fallback_prompt
    args.setdefault("prompt", prompt)
    return {"tool": tool, "args": args, "prompt": prompt, "notice": bool(data.get("notice"))}


def enforce_tool_plan(plan: dict[str, Any], fallback_prompt: str) -> dict[str, Any]:
    return sanitize_tool_plan(plan, fallback_prompt)


def sanitize_tool_plan(plan: dict[str, Any], fallback_prompt: str) -> dict[str, Any]:
    text = str(fallback_prompt or "")
    tool = str(plan.get("tool") or "chat")
    args = plan.get("args") if isinstance(plan.get("args"), dict) else {}
    args = dict(args)
    prompt = str(args.get("prompt") or plan.get("prompt") or text).strip() or text
    args["prompt"] = prompt
    if tool == "calculator":
        expression = str(args.get("expression") or prompt or text).strip()
        args["expression"] = expression
        return {"tool": "calculator", "args": args, "prompt": prompt, "notice": False}
    if tool == "weather":
        inferred_location = infer_weather_location(text)
        args["location"] = normalize_weather_location(str(args.get("location") or ""), inferred_location)
        args["date"] = str(args.get("date") or infer_weather_date(text)).strip()
        return {"tool": "weather", "args": args, "prompt": prompt, "notice": True}
    return {"tool": tool, "args": args, "prompt": prompt, "notice": bool(plan.get("notice"))}


def is_weather_query(text: str) -> bool:
    return bool(WEATHER_QUERY_RE.search(str(text or "")))


def infer_weather_date(text: str) -> str:
    value = str(text or "")
    if "大后天" in value:
        target = datetime.now().date() + timedelta(days=3)
        return target.isoformat()
    if "后天" in value:
        return "after_tomorrow"
    if "明天" in value or "明日" in value:
        return "tomorrow"
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", value)
    if match:
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return "today"


def infer_weather_location(text: str) -> str:
    value = re.sub(r"@\S+", "", str(text or "")).strip()
    value = re.sub(r"[，。！？,.?！\s]+", " ", value).strip()
    date_pattern = "|".join(re.escape(token) for token in sorted(DATE_TOKENS, key=len, reverse=True))
    weather_pattern = r"天气|气温|温度|降雨|下雨|下雪|风力|风速|湿度|穿衣|冷不冷|热不热"
    value = re.sub(rf"^({date_pattern})+", " ", value)
    value = re.sub(rf"({date_pattern})+$", " ", value)
    value = re.sub(rf"(?<=[\u4e00-\u9fff])({date_pattern})(?={weather_pattern})", " ", value)
    for token in LOCATION_PREFIX_WORDS:
        value = value.replace(token, " ")
    value = re.sub(r"[，。！？,.?！\s]+", " ", value).strip()
    value = re.sub(rf"^({date_pattern})+", " ", value)
    value = re.sub(rf"({date_pattern})+$", " ", value)
    for token in LOCATION_STOP_WORDS:
        value = value.replace(token, " ")
    value = re.sub(r"[，。！？,.?！\s]+", " ", value).strip()
    parts = [part.strip() for part in value.split(" ") if part.strip()]
    return parts[0] if parts else ""


def normalize_weather_location(candidate: str, fallback: str = "") -> str:
    value = re.sub(r"@\S+", "", str(candidate or "")).strip()
    value = re.split(r"[,，/、\s]+", value, maxsplit=1)[0].strip()
    value = re.sub(r"[。！？?!.]+$", "", value).strip()
    fallback = str(fallback or "").strip()
    bad_values = {"", "我", "你", "我问你", "问你", "明天", "后天", "今天", "天气", "气温", "温度"}
    if value in bad_values:
        return fallback
    if fallback and len(value) == 1 and fallback.startswith(value):
        return fallback
    if fallback and len(value) > len(fallback) and fallback in value:
        return fallback
    return value or fallback


def weather_context(location: str, date_value: str) -> str:
    location = str(location or "").strip()
    if not location:
        raise ProviderError("天气工具缺少地点")
    target_date = _normalize_weather_date(date_value)
    place = client.geocode(location)
    forecast = client.weather_forecast(float(place["latitude"]), float(place["longitude"]), target_date)
    daily = forecast.get("daily") if isinstance(forecast.get("daily"), dict) else {}
    times = daily.get("time") if isinstance(daily.get("time"), list) else []
    try:
        index = times.index(target_date)
    except ValueError as exc:
        raise ProviderError("天气接口没有返回目标日期") from exc
    code = _daily_value(daily, "weather_code", index)
    text = WEATHER_CODE_TEXT.get(int(code or -1), f"天气代码 {code}")
    high = _daily_value(daily, "temperature_2m_max", index)
    low = _daily_value(daily, "temperature_2m_min", index)
    rain = _daily_value(daily, "precipitation_probability_max", index)
    wind = _daily_value(daily, "wind_speed_10m_max", index)
    current = forecast.get("current") if isinstance(forecast.get("current"), dict) else {}
    current_line = ""
    if current:
        temp = current.get("temperature_2m")
        apparent = current.get("apparent_temperature")
        current_line = f"\n当前：{temp}℃，体感 {apparent}℃" if temp is not None else ""
    return (
        "实时天气工具结果：\n"
        "数据源：Open-Meteo 实时天气接口\n"
        f"地点：{place.get('name')} {place.get('admin1') or ''} {place.get('country') or ''}\n"
        f"目标日期：{target_date}\n"
        f"目标日期天气：{text}\n"
        f"目标日期温度：{low}℃ - {high}℃\n"
        f"目标日期降雨概率：{rain}%\n"
        f"目标日期最大风速：{wind} km/h"
        f"{current_line}\n"
        "请基于这个天气工具结果回答。目标日期就是用户要问的日期，不要重新推算今天/明天/后天，不要说没查到，不要建议用户再去天气网站查询。"
    )


def weather_context_with_repair(question: str, args: dict[str, Any]) -> str:
    cleaned_location = infer_weather_location(question)
    location = normalize_weather_location(str(args.get("location") or ""), cleaned_location)
    date_value = str(args.get("date") or infer_weather_date(question)).strip()
    try:
        return weather_context(location, date_value)
    except ProviderError as first_exc:
        candidates: list[tuple[str, str]] = []
        if cleaned_location and cleaned_location != location:
            candidates.append((cleaned_location, date_value))
        try:
            repaired = repair_weather_args(question, args, str(first_exc))
            fixed_location = str(repaired.get("location") or "").strip()
            fixed_date = str(repaired.get("date") or date_value).strip()
            if fixed_location and (fixed_location, fixed_date) not in candidates:
                candidates.append((fixed_location, fixed_date))
        except Exception:
            pass
        for candidate_location, candidate_date in candidates:
            try:
                return weather_context(candidate_location, candidate_date)
            except ProviderError:
                continue
        raise first_exc


def weather_reply_from_context(context: str) -> str:
    data: dict[str, str] = {}
    for raw_line in str(context or "").splitlines():
        line = raw_line.strip()
        if not line or "：" not in line:
            continue
        key, _, value = line.partition("：")
        data[key.strip()] = value.strip()
    location = data.get("地点", "")
    date = data.get("目标日期", "")
    weather = data.get("目标日期天气", "")
    temp = data.get("目标日期温度", "")
    rain = data.get("目标日期降雨概率", "")
    wind = data.get("目标日期最大风速", "")
    parts = []
    if location or date:
        parts.append(f"{location} {date}".strip())
    if weather:
        parts.append(weather)
    if temp:
        parts.append(f"温度 {temp}")
    if rain:
        parts.append(f"降雨概率 {rain}")
    if wind:
        parts.append(f"最大风速 {wind}")
    if not parts:
        raise ProviderError("天气工具结果为空")
    tip = _weather_tip(weather, rain, temp)
    return "，".join(parts) + f"。\n{tip}"


def _weather_tip(weather: str, rain: str, temp: str) -> str:
    text = f"{weather} {rain} {temp}"
    if any(word in text for word in ("雨", "降雨", "雷暴")):
        return "建议带伞，出门别太相信天空的脸色。"
    if any(word in text for word in ("雪", "冰雹")):
        return "注意保暖和路面湿滑。"
    return "正常出门就行，临出门再看一眼实时变化。"


def repair_weather_args(question: str, failed_args: dict[str, Any], error: str) -> dict[str, str]:
    prompt = (
        "你是天气工具参数修复器，只输出 JSON，不要解释。\n"
        "根据用户原问题、失败参数和错误原因，修正天气工具参数。\n"
        "要求：location 必须是完整地点名，不要截断，例如“昆明”不能写成“昆”；"
        "date 只能是 today、tomorrow、after_tomorrow 或 YYYY-MM-DD。\n"
        f"用户原问题：{question}\n"
        f"失败参数：{json.dumps(failed_args, ensure_ascii=False)}\n"
        f"错误原因：{error}\n"
        '输出格式：{"location":"完整地点","date":"today|tomorrow|after_tomorrow|YYYY-MM-DD"}'
    )
    text = client.chat(
        settings.intent,
        system_prompt="只输出 JSON。",
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        data = json.loads(text)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    location = str(data.get("location") or "").strip()
    location = re.split(r"[,，/、\s]+", location, maxsplit=1)[0].strip()
    date_value = str(data.get("date") or failed_args.get("date") or infer_weather_date(question)).strip()
    return {"location": location, "date": date_value}


def _normalize_weather_date(value: str) -> str:
    raw = str(value or "").strip().lower()
    today = datetime.now().date()
    if raw in {"", "today", "今天"}:
        return today.isoformat()
    if raw in {"tomorrow", "明天"}:
        return (today + timedelta(days=1)).isoformat()
    if raw in {"after_tomorrow", "后天"}:
        return (today + timedelta(days=2)).isoformat()
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date().isoformat()
    except Exception:
        return today.isoformat()


def _daily_value(daily: dict[str, Any], key: str, index: int) -> Any:
    values = daily.get(key)
    if not isinstance(values, list) or index >= len(values):
        return ""
    return values[index]
