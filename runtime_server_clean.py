from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse

import runtime_server_v34 as runtime

ROOT = Path(__file__).resolve().parent
core = runtime.core

# Keep all existing backend/API/coin routes inside the original app, but own
# the main and stock-detail pages here so legacy UI patchers cannot re-inject
# old JavaScript/CSS into the pages users actually see.
app = FastAPI(title="Namuh Smart Trader Clean Frontend")


@app.get("/", include_in_schema=False)
def clean_home():
    return FileResponse(ROOT / "static" / "rebuild-index.html")


@app.get("/stock/{market}/{code}", include_in_schema=False)
def clean_stock(market: str, code: str):
    return FileResponse(ROOT / "static" / "rebuild-stock.html")


# Everything else is delegated unchanged: /api/*, /static/*, /coin/*,
# /index/*, health endpoints, trading endpoints, etc.
app.mount("/", core.app)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8081")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
