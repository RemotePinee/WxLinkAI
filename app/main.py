from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .router import router
from .config import BASE_DIR


app = FastAPI(title="WxLinkAI", version="0.1.0")
app.include_router(router)

WEB_DIR = BASE_DIR / "web"
if WEB_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")


@app.get("/")
def console_index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")
