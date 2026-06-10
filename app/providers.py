from __future__ import annotations

import base64
import json
import re
from typing import Any

import httpx

from .config import ProviderConfig, settings


class ProviderError(RuntimeError):
    pass


def _response_error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except Exception:
        text = str(response.text or "").strip()
        return text or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("error") or error).strip()
        if error:
            return str(error).strip()
        detail = body.get("detail")
        if isinstance(detail, dict):
            return str(detail.get("error") or detail.get("message") or detail).strip()
        if detail:
            return str(detail).strip()
    return f"HTTP {response.status_code}"


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ProviderError(_response_error_message(response)) from exc


def _first_markdown_image_url(text: str) -> str:
    match = re.search(r"!\[[^\]]*]\(([^)\s]+)\)", str(text or ""))
    return match.group(1).strip() if match else ""


def _headers(api_key: str) -> dict[str, str]:
    if not str(api_key or "").strip():
        raise ProviderError("missing provider api key")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def _anthropic_headers(api_key: str) -> dict[str, str]:
    if not str(api_key or "").strip():
        raise ProviderError("missing provider api key")
    return {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }


def _data_url(image_bytes: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"


def _protocol_api(protocol: str) -> str:
    if protocol == "responses":
        return "/v1/responses"
    if protocol == "anthropic_messages":
        return "/v1/messages"
    if protocol == "chat_stream":
        return "/api/chat/stream"
    return "/v1/chat/completions"


def _parse_chat_response(protocol: str, payload: dict[str, Any]) -> str:
    if protocol == "responses":
        output_text = str(payload.get("output_text") or "").strip()
        if output_text:
            return output_text
        output = payload.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                for content in item.get("content") or []:
                    if isinstance(content, dict):
                        text = str(content.get("text") or "").strip()
                        if text:
                            parts.append(text)
            return "\n".join(parts).strip()
        return ""
    if protocol == "anthropic_messages":
        content = payload.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = str(item.get("text") or "").strip()
                    if text:
                        parts.append(text)
            return "\n".join(parts).strip()
        return ""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message")
        if isinstance(message, dict):
            return str(message.get("content") or "").strip()
        return str(first.get("text") or "").strip()
    return ""


def _extract_response_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        item: dict[str, Any] = {"role": "assistant" if role == "assistant" else "user"}
        if isinstance(content, list):
            parts: list[dict[str, Any]] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    parts.append({"type": "input_text", "text": str(part.get("text") or "")})
                elif part.get("type") == "image_url":
                    image_url = part.get("image_url") or {}
                    parts.append({"type": "input_image", "image_url": str(image_url.get("url") or "")})
            item["content"] = parts
        else:
            item["content"] = [{"type": "input_text", "text": str(content or "")}]
        out.append(item)
    return out


def _extract_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        item: dict[str, Any] = {"role": "assistant" if role == "assistant" else "user"}
        if isinstance(content, list):
            parts: list[dict[str, Any]] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    parts.append({"type": "text", "text": str(part.get("text") or "")})
                elif part.get("type") == "image_url":
                    image_url = part.get("image_url") or {}
                    url = str(image_url.get("url") or "")
                    if url.startswith("data:"):
                        header, _, data = url.partition(",")
                        mime = header.split(";")[0].removeprefix("data:")
                        parts.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime or "image/png",
                                "data": data,
                            },
                        })
            item["content"] = parts
        else:
            item["content"] = str(content or "")
        out.append(item)
    return out


def _parse_sse_text(text: str) -> str:
    parts: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            item = json.loads(payload)
        except Exception:
            continue
        if str(item.get("type") or "") == "delta":
            parts.append(str(item.get("text") or ""))
    return "".join(parts).strip()


class OpenAICompatibleClient:
    def __init__(self) -> None:
        self.http = httpx.Client(timeout=120)

    def _image_timeout(self) -> int:
        return int(settings.image_generation_timeout_seconds or 360)

    def geocode(self, location: str) -> dict[str, Any]:
        endpoint = "https://geocoding-api.open-meteo.com/v1/search"
        params = {
            "name": location,
            "count": 1,
            "language": "zh",
            "format": "json",
        }
        response = self.http.get(endpoint, params=params, timeout=10)
        _raise_for_status(response)
        body = response.json()
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list) or not results:
            raise ProviderError(f"没有找到地点：{location}")
        item = results[0]
        if not isinstance(item, dict):
            raise ProviderError(f"地点结果异常：{location}")
        if item.get("latitude") is None or item.get("longitude") is None:
            raise ProviderError(f"地点缺少经纬度：{location}")
        return item

    def weather_forecast(self, latitude: float, longitude: float, target_date: str) -> dict[str, Any]:
        endpoint = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
            "timezone": "Asia/Shanghai",
            "start_date": target_date,
            "end_date": target_date,
        }
        response = self.http.get(endpoint, params=params, timeout=12)
        _raise_for_status(response)
        body = response.json()
        if not isinstance(body, dict):
            raise ProviderError("天气接口返回异常")
        return body

    def search(self, query: str) -> list[dict[str, str]]:
        if not settings.search_enabled or not settings.search_base_url:
            return []
        endpoint = settings.search_base_url.rstrip("/") + "/search"
        params = {
            "q": query,
            "format": "json",
            "language": "zh-CN",
            "safesearch": "0",
        }
        response = self.http.get(endpoint, params=params, timeout=settings.search_timeout_seconds)
        _raise_for_status(response)
        body = response.json()
        raw_results = body.get("results")
        if not isinstance(raw_results, list):
            return []
        results: list[dict[str, str]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            content = str(item.get("content") or item.get("snippet") or "").strip()
            if not title and not content:
                continue
            results.append({
                "title": title,
                "url": url,
                "content": content,
            })
            if len(results) >= settings.search_max_results:
                break
        return results

    def _download_image_b64(self, url: str) -> str:
        value = str(url or "").strip()
        if not value:
            return ""
        if value.startswith("data:image/") and "," in value:
            return value.split(",", 1)[1].strip()
        response = self.http.get(value, timeout=self._image_timeout())
        _raise_for_status(response)
        return base64.b64encode(response.content).decode("ascii")

    def _image_b64_from_items(self, data: object) -> list[str]:
        if not isinstance(data, list):
            return []
        results: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            b64 = str(item.get("b64_json") or "").strip()
            if b64:
                results.append(b64)
                continue
            url = str(item.get("url") or "").strip()
            if url:
                image_b64 = self._download_image_b64(url)
                if image_b64:
                    results.append(image_b64)
        return results

    def chat(
        self,
        provider: ProviderConfig,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.3,
    ) -> str:
        endpoint = provider.base_url.rstrip("/") + _protocol_api(provider.protocol)
        if provider.protocol == "responses":
            payload = {
                "model": provider.model,
                "instructions": system_prompt,
                "input": _extract_response_input(messages),
                "temperature": temperature,
            }
            headers = _headers(provider.api_key)
            response = self.http.post(endpoint, headers=headers, json=payload)
            _raise_for_status(response)
            text = _parse_chat_response(provider.protocol, response.json())
        elif provider.protocol == "anthropic_messages":
            payload = {
                "model": provider.model,
                "system": system_prompt,
                "messages": _extract_anthropic_messages(messages),
                "max_tokens": 2048,
                "temperature": temperature,
            }
            headers = _anthropic_headers(provider.api_key)
            response = self.http.post(endpoint, headers=headers, json=payload)
            _raise_for_status(response)
            text = _parse_chat_response(provider.protocol, response.json())
        elif provider.protocol == "chat_stream":
            final_messages = [{"role": "system", "content": system_prompt}]
            final_messages.extend(messages)
            payload = {
                "model": provider.model,
                "messages": final_messages,
            }
            if provider.account_type:
                payload["account_type"] = provider.account_type
            headers = _headers(provider.api_key)
            response = self.http.post(endpoint, headers=headers, json=payload)
            _raise_for_status(response)
            text = _parse_sse_text(response.text)
        else:
            final_messages = [{"role": "system", "content": system_prompt}]
            final_messages.extend(messages)
            payload = {
                "model": provider.model,
                "messages": final_messages,
                "temperature": temperature,
            }
            headers = _headers(provider.api_key)
            response = self.http.post(endpoint, headers=headers, json=payload)
            _raise_for_status(response)
            text = _parse_chat_response(provider.protocol, response.json())
        if not text:
            raise ProviderError("empty chat response")
        return text

    def generate_image(self, prompt: str, resolution: str = "", size: str = "") -> list[str]:
        endpoint = settings.image.base_url.rstrip("/") + settings.image_api
        payload: dict[str, Any] = {
            "prompt": prompt,
            "model": settings.image.model,
            "n": 1,
            "response_format": "b64_json",
        }
        if resolution:
            payload["resolution"] = resolution
        if size:
            payload["size"] = size
        response = self.http.post(endpoint, headers=_headers(settings.image.api_key), json=payload, timeout=self._image_timeout())
        _raise_for_status(response)
        data = response.json().get("data")
        if not isinstance(data, list):
            raise ProviderError("image response missing data")
        return self._image_b64_from_items(data)

    def edit_image(self, prompt: str, image_bytes: bytes, mime: str, resolution: str = "", size: str = "") -> list[str]:
        endpoint = settings.image.base_url.rstrip("/") + settings.image_edit_api
        data: dict[str, Any] = {
            "prompt": prompt,
            "model": settings.image.model,
            "n": "1",
            "response_format": "b64_json",
        }
        if resolution:
            data["resolution"] = resolution
        if size:
            data["size"] = size
        headers = {"Authorization": f"Bearer {settings.image.api_key}"}
        files = {"image": ("wechat-image.jpg", image_bytes, mime or "image/jpeg")}
        response = self.http.post(endpoint, headers=headers, data=data, files=files, timeout=self._image_timeout())
        _raise_for_status(response)
        body = response.json()
        data = body.get("data")
        images = self._image_b64_from_items(data)
        if images:
            return images
        text = _parse_chat_response("chat_completions", body)
        marker = "base64,"
        idx = text.find(marker)
        if idx >= 0:
            value = text[idx + len(marker):]
            end = value.find(")")
            if end > 0:
                value = value[:end]
            return [value.strip()]
        image_url = _first_markdown_image_url(text)
        if image_url:
            return [self._download_image_b64(image_url)]
        if isinstance(data, list):
            raise ProviderError("image edit response missing image")
        else:
            raise ProviderError("image edit response missing image")

    def visual_chat(self, prompt: str, image_bytes: bytes, mime: str) -> str:
        endpoint = settings.image.base_url.rstrip("/") + settings.image_chat_api
        persona = str(settings.persona or "").strip()
        payload: dict[str, Any] = {
            "model": settings.visual_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "直接回答用户关于图片的问题，中文优先。"
                        + (persona if persona else "")
                        + "不要因为来源是微信就降低信息量或变得过度保守；能判断的内容直接说明，不确定的地方再标注不确定。"
                        + "回复适合聊天阅读，不要整段堆在一起。"
                        + "允许使用短段落、空行、- 列表、1. 2. 3. 编号列表。"
                        + "可以在该有情绪表达的地方少量使用 emoji，每条最多 1-2 个，没必要就不用。"
                        + "不要使用 Markdown 强调或代码块，不要使用 **、```、#。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": _data_url(image_bytes, mime)}},
                    ],
                },
            ],
            "temperature": 0.2,
        }
        if settings.image.account_type:
            payload["account_type"] = settings.image.account_type
        response = self.http.post(endpoint, headers=_headers(settings.image.api_key), json=payload)
        _raise_for_status(response)
        text = _parse_chat_response("chat_completions", response.json())
        if not text:
            raise ProviderError("empty visual response")
        return text


def build_intent_system_prompt() -> str:
    return (
        "你是微信群机器人路由器。"
        "只输出 JSON，不要解释。"
        '格式：{"action":"chat|draw","prompt":"清理后的文本","use_image":true|false,"resolution":"|2k|4k","size":"|1:1|16:9|9:16|4:3|3:4","notice":true|false,"notice_text":"短提示"}。'
        "明确要求画图、生图、生成图片、改图时 action=draw，否则 action=chat。"
        "如果用户在问图、参考图、改图、图里有什么、根据图片生成，则 use_image=true，否则 false。"
        "如果输入里带有图片上下文，用户说换场景、换背景、换风格、改一下、变高级、重画、二创等省略说法，也视为基于最近图片的图生图：action=draw,use_image=true。"
        "明确提到 2K/2048 输出 2k；明确提到 4K/3840/4096/超清 输出 4k；否则空字符串。"
        "明确提到方图/正方形/1:1 输出 size=1:1；横版/宽屏/16:9 输出 16:9；竖版/手机壁纸/9:16 输出 9:16；4:3 输出 4:3；3:4 输出 3:4；否则空字符串。"
        "notice 用于聊天自动提示：只有当用户请求可能耗时较长时才为 true，例如查询资料、比价、找航班/车次、整理大量信息、写方案、长文本分析、复杂计算、多步骤处理。"
        "简单问候、简短问答、普通闲聊、能直接一句话回答的问题，notice=false。"
        "notice=true 时 notice_text 固定输出：正在核对信息，稍后回复。"
        "notice=false 时 notice_text 为空字符串。"
    )


def parse_intent(text: str, fallback_prompt: str) -> dict[str, Any]:
    try:
        obj = json.loads(text)
    except Exception:
        return {"action": "chat", "prompt": fallback_prompt, "use_image": False, "resolution": "", "size": "", "notice": False, "notice_text": ""}
    if not isinstance(obj, dict):
        return {"action": "chat", "prompt": fallback_prompt, "use_image": False, "resolution": "", "size": "", "notice": False, "notice_text": ""}
    action = str(obj.get("action") or "chat").strip().lower()
    if action not in {"chat", "draw"}:
        action = "chat"
    prompt = str(obj.get("prompt") or fallback_prompt).strip() or fallback_prompt
    resolution = str(obj.get("resolution") or "").strip().lower()
    if resolution not in {"", "2k", "4k"}:
        resolution = ""
    size = str(obj.get("size") or "").strip().lower()
    if size not in {"", "1:1", "16:9", "9:16", "4:3", "3:4"}:
        size = ""
    return {
        "action": action,
        "prompt": prompt,
        "use_image": bool(obj.get("use_image")),
        "resolution": resolution,
        "size": size,
        "notice": bool(obj.get("notice")),
        "notice_text": str(obj.get("notice_text") or "").strip(),
    }


client = OpenAICompatibleClient()
