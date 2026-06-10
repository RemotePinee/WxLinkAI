from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from .config import IMAGES_DIR, STATE_FILE, settings


class BridgeState:
    def __init__(self, state_file: Path) -> None:
        self.state_file = state_file
        self.lock = threading.Lock()
        self.event_lock = threading.Lock()
        self.data = self._load()
        self.events: list[dict[str, Any]] = []
        self.event_seq = 0

    def _load(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"sessions": {}, "images": {}}
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return {"sessions": {}, "images": {}}
        if not isinstance(raw, dict):
            return {"sessions": {}, "images": {}}
        raw.setdefault("sessions", {})
        raw.setdefault("images", {})
        return raw

    def _save(self) -> None:
        self.state_file.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def append_event(self, level: str, message: str) -> dict[str, Any]:
        item = {
            "seq": 0,
            "ts": int(time.time()),
            "level": str(level or "info"),
            "message": str(message or ""),
        }
        with self.event_lock:
            self.event_seq += 1
            item["seq"] = self.event_seq
            self.events.append(item)
            if len(self.events) > 500:
                self.events = self.events[-500:]
        return item

    def get_events(self, after_seq: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self.event_lock:
            if after_seq <= 0:
                return self.events[-max(1, limit):]
            items = [item for item in self.events if int(item.get("seq") or 0) > after_seq]
            return items[: max(1, limit)]

    def append_history(self, session_key: str, role: str, content: str) -> None:
        with self.lock:
            session = self.data["sessions"].setdefault(session_key, {"history": [], "updated_at": 0})
            history = session.setdefault("history", [])
            history.append({"role": role, "content": str(content or "")})
            while len(history) > settings.history_limit:
                history.pop(0)
            session["updated_at"] = int(time.time())
            self._save()

    def get_history(self, session_key: str) -> list[dict[str, str]]:
        with self.lock:
            session = self.data["sessions"].get(session_key) or {}
            history = session.get("history")
            if not isinstance(history, list):
                return []
            return [item for item in history if isinstance(item, dict)]

    def clear_history(self, session_key: str) -> bool:
        with self.lock:
            session = self.data["sessions"].get(session_key)
            if not isinstance(session, dict):
                return False
            had_history = bool(session.get("history"))
            session["history"] = []
            session["updated_at"] = int(time.time())
            self._save()
            return had_history

    def remember_image(self, session_key: str, image_b64: str, mime: str) -> str:
        image_bytes = base64.b64decode(image_b64)
        suffix = "png"
        if "/" in mime:
            suffix = mime.split("/", 1)[1].split(";", 1)[0] or "png"
        digest = hashlib.md5(image_bytes).hexdigest()
        filename = f"{int(time.time())}_{digest}.{suffix}"
        path = IMAGES_DIR / filename
        path.write_bytes(image_bytes)
        with self.lock:
            self.data["images"][session_key] = {
                "path": str(path),
                "mime": mime,
                "updated_at": int(time.time()),
            }
            self._save()
        return str(path)

    def get_recent_image(self, session_key: str) -> tuple[bytes, str] | None:
        with self.lock:
            item = self.data["images"].get(session_key)
            if not isinstance(item, dict):
                return None
            updated_at = int(item.get("updated_at") or 0)
            if int(time.time()) - updated_at > settings.image_ttl_seconds:
                return None
            path = Path(str(item.get("path") or ""))
            mime = str(item.get("mime") or "image/png")
        if not path.is_file():
            return None
        return path.read_bytes(), mime


bridge_state = BridgeState(STATE_FILE)
