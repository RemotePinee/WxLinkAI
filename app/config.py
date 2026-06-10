from __future__ import annotations

import json
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
STATE_FILE = DATA_DIR / "bridge_state.json"
CONFIG_FILE = BASE_DIR / "config.json"
CONFIG_TEMPLATE_FILE = BASE_DIR / "config.example.json"


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    api_key: str
    protocol: str
    model: str
    account_type: str = ""


@dataclass(frozen=True)
class Settings:
    auth_key: str
    host: str
    port: int
    routing_mode: str
    history_limit: int
    history_user_max_chars: int
    history_assistant_max_chars: int
    image_ttl_seconds: int
    image_generation_timeout_seconds: int
    chat: ProviderConfig
    intent: ProviderConfig
    image: ProviderConfig
    image_api: str
    image_chat_api: str
    image_edit_api: str
    visual_model: str
    visual_chat_provider: str
    persona: str
    search_enabled: bool
    search_base_url: str
    search_timeout_seconds: int
    search_max_results: int


def _cfg_bool(config: dict[str, object], key: str, default: bool = False) -> bool:
    value = str(config.get(key, default) or "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _read_config_file() -> dict[str, object]:
    if not CONFIG_FILE.exists():
        _ensure_config_file()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _ensure_config_file() -> None:
    if CONFIG_FILE.exists():
        return
    if CONFIG_TEMPLATE_FILE.exists():
        shutil.copyfile(CONFIG_TEMPLATE_FILE, CONFIG_FILE)
        return
    CONFIG_FILE.write_text("{}\n", encoding="utf-8")


def _read_template_file() -> dict[str, object]:
    if not CONFIG_TEMPLATE_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_TEMPLATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _merge_missing_fields(config: dict[str, object], defaults: dict[str, object]) -> dict[str, object]:
    merged: dict[str, object] = dict(config)
    for key, default_value in defaults.items():
        current_value = merged.get(key)
        if isinstance(default_value, dict):
            current_dict = current_value if isinstance(current_value, dict) else {}
            merged[key] = _merge_missing_fields(current_dict, default_value)
        elif key not in merged:
            merged[key] = default_value
    return merged


def read_config_file() -> dict[str, object]:
    return _read_config_file()


def save_config_file(config: dict[str, object]) -> None:
    config = _merge_missing_fields(config, _read_template_file())
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _cfg_value(config: dict[str, object], key: str, default: str = "") -> str:
    return str(config.get(key, default) or "").strip()


def _cfg_section(config: dict[str, object], key: str) -> dict[str, object]:
    value = config.get(key)
    return value if isinstance(value, dict) else {}


def _resolve(name: str, config_value: str, default: str = "") -> str:
    env_value = _env(name)
    if env_value:
        return env_value
    return str(config_value or default).strip()


def load_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    config = _read_config_file()
    chat_cfg = _cfg_section(config, "chat")
    intent_cfg = _cfg_section(config, "intent")
    image_cfg = _cfg_section(config, "image")
    search_cfg = _cfg_section(config, "search")

    chat = ProviderConfig(
        base_url=_resolve("CHAT_BASE_URL", _cfg_value(chat_cfg, "base_url"), "https://api.deepseek.com"),
        api_key=_resolve("CHAT_API_KEY", _cfg_value(chat_cfg, "api_key")),
        protocol=_resolve("CHAT_PROTOCOL", _cfg_value(chat_cfg, "protocol"), "chat_completions"),
        model=_resolve("CHAT_MODEL", _cfg_value(chat_cfg, "model"), "deepseek-chat"),
        account_type=_resolve("CHAT_ACCOUNT_TYPE", _cfg_value(chat_cfg, "account_type")),
    )
    intent = ProviderConfig(
        base_url=_resolve("INTENT_BASE_URL", _cfg_value(intent_cfg, "base_url"), chat.base_url),
        api_key=_resolve("INTENT_API_KEY", _cfg_value(intent_cfg, "api_key"), chat.api_key),
        protocol=_resolve("INTENT_PROTOCOL", _cfg_value(intent_cfg, "protocol"), chat.protocol),
        model=_resolve("INTENT_MODEL", _cfg_value(intent_cfg, "model"), "auto"),
        account_type=_resolve("INTENT_ACCOUNT_TYPE", _cfg_value(intent_cfg, "account_type")),
    )
    image = ProviderConfig(
        base_url=_resolve("IMAGE_BASE_URL", _cfg_value(image_cfg, "base_url"), "http://127.0.0.1:3030"),
        api_key=_resolve("IMAGE_API_KEY", _cfg_value(image_cfg, "api_key")),
        protocol=_resolve("IMAGE_PROTOCOL", _cfg_value(image_cfg, "protocol"), "chatgpt2api"),
        model=_resolve("IMAGE_MODEL", _cfg_value(image_cfg, "model"), "gpt-image-2"),
        account_type=_resolve("IMAGE_ACCOUNT_TYPE", _cfg_value(image_cfg, "account_type")),
    )
    return Settings(
        auth_key=_resolve("BRIDGE_AUTH_KEY", _cfg_value(config, "auth_key"), "change-me"),
        host=_resolve("BRIDGE_HOST", _cfg_value(config, "host"), "0.0.0.0"),
        port=int(_resolve("BRIDGE_PORT", _cfg_value(config, "port"), "8090") or "8090"),
        routing_mode=_resolve("ROUTING_MODE", _cfg_value(config, "routing_mode"), "hybrid"),
        history_limit=max(1, int(_resolve("HISTORY_LIMIT", _cfg_value(config, "history_limit"), "8") or "8")),
        history_user_max_chars=max(40, int(_resolve("HISTORY_USER_MAX_CHARS", _cfg_value(config, "history_user_max_chars"), "300") or "300")),
        history_assistant_max_chars=max(80, int(_resolve("HISTORY_ASSISTANT_MAX_CHARS", _cfg_value(config, "history_assistant_max_chars"), "600") or "600")),
        image_ttl_seconds=max(60, int(_resolve("IMAGE_TTL_SECONDS", _cfg_value(config, "image_ttl_seconds"), "600") or "600")),
        image_generation_timeout_seconds=max(60, int(_resolve("IMAGE_GENERATION_TIMEOUT_SECONDS", _cfg_value(config, "image_generation_timeout_seconds"), "360") or "360")),
        chat=chat,
        intent=intent,
        image=image,
        image_api=_resolve("IMAGE_API", _cfg_value(image_cfg, "api"), "/v1/images/generations"),
        image_chat_api=_resolve("IMAGE_CHAT_API", _cfg_value(image_cfg, "chat_api"), "/v1/chat/completions"),
        image_edit_api=_resolve("IMAGE_EDIT_API", _cfg_value(image_cfg, "edit_api"), "/v1/images/edits"),
        visual_model=_resolve("VISUAL_MODEL", _cfg_value(image_cfg, "visual_model"), intent.model),
        visual_chat_provider=_resolve("VISUAL_CHAT_PROVIDER", _cfg_value(config, "visual_chat_provider"), "intent"),
        persona=_resolve("PERSONA", _cfg_value(config, "persona"), ""),
        search_enabled=_cfg_bool(search_cfg, "enabled", False),
        search_base_url=_resolve("SEARCH_BASE_URL", _cfg_value(search_cfg, "base_url"), ""),
        search_timeout_seconds=max(3, int(_resolve("SEARCH_TIMEOUT_SECONDS", _cfg_value(search_cfg, "timeout_seconds"), "12") or "12")),
        search_max_results=max(1, min(8, int(_resolve("SEARCH_MAX_RESULTS", _cfg_value(search_cfg, "max_results"), "5") or "5"))),
    )


class SettingsProxy:
    def __init__(self, current: Settings) -> None:
        self._lock = threading.RLock()
        self._current = current

    def reload(self) -> Settings:
        current = load_settings()
        with self._lock:
            self._current = current
        return current

    def snapshot(self) -> Settings:
        with self._lock:
            return self._current

    def __getattr__(self, name: str) -> object:
        with self._lock:
            return getattr(self._current, name)


settings = SettingsProxy(load_settings())


def reload_settings() -> Settings:
    return settings.reload()
