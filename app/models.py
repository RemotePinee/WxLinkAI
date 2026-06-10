from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class WechatMessageRequest(BaseModel):
    talker: str = Field(..., min_length=1)
    sender: str = Field(..., min_length=1)
    text: str = ""
    at_me: bool = False
    notice_sent: bool = False
    client_task_id: str = ""
    response_format: str = ""
    image_b64: str = ""
    image_mime: str = "image/png"
    intent_action: str = ""
    intent_prompt: str = ""
    intent_use_image: str = ""
    intent_resolution: str = ""
    intent_size: str = ""
    intent_notice: str = ""
    intent_notice_text: str = ""


class WechatIntentRequest(BaseModel):
    talker: str = Field(..., min_length=1)
    sender: str = Field(..., min_length=1)
    text: str = ""
    at_me: bool = False


class WechatImageCacheRequest(BaseModel):
    talker: str = Field(..., min_length=1)
    sender: str = Field(..., min_length=1)
    image_b64: str = Field(..., min_length=1)
    image_mime: str = "image/png"


class WechatBridgeResponse(BaseModel):
    mode: Literal["chat", "draw", "error"]
    reply_text: str = ""
    images_b64: list[str] = Field(default_factory=list)
    session_key: str = ""
    used_image: bool = False
    task_id: str = ""
