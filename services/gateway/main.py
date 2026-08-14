from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from services.gateway.deps import GatewaySettings
from services.gateway.factory import build_reference_preview_service, build_shooting_loop
from services.gateway.routes.sessions import router as sessions_router
from services.gateway.session_store import InMemorySessionStore
from utils import load_config
from utils.file import ensure_dir
from utils.logger import configure_logging


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_under_root(root: Path, value: Path | str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def create_app(
    config: dict[str, Any] | None = None,
    *,
    attach_loop: bool = True,
) -> FastAPI:
    root = _repo_root()
    if config is None:
        config_path = Path(os.environ.get("CAMERAAGENT_CONFIG", root / "config.yaml"))
        if not config_path.is_absolute():
            config_path = root / config_path
        config = load_config(config_path)

    logging_cfg = config.get("logging")
    if isinstance(logging_cfg, dict):
        configure_logging(config=logging_cfg)
    else:
        configure_logging(str(logging_cfg or "INFO"))

    gateway_cfg = dict(config.get("gateway") or {})
    web_dir = _resolve_under_root(
        root, gateway_cfg.get("web_dir", root / "frontend" / "web")
    )
    frames_dir = ensure_dir(
        _resolve_under_root(
            root, gateway_cfg.get("frames_dir", root / "outputs" / "gateway_frames")
        )
    )
    plans_dir = ensure_dir(
        _resolve_under_root(
            root, gateway_cfg.get("plans_dir", root / "outputs" / "plans")
        )
    )
    previews_dir = ensure_dir(
        _resolve_under_root(
            root, gateway_cfg.get("previews_dir", root / "outputs" / "reference_previews")
        )
    )

    settings = GatewaySettings(
        demo_token=str(gateway_cfg.get("demo_token") or ""),
        max_frame_long_edge=int(gateway_cfg.get("max_frame_long_edge") or 1280),
        frames_dir=frames_dir,
        plans_dir=plans_dir,
        previews_dir=previews_dir,
        web_dir=web_dir,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.attach_loop and app.state.shooting_loop is None:
            app.state.shooting_loop = build_shooting_loop(app.state.config)
        if app.state.attach_loop and app.state.reference_preview_service is None:
            app.state.reference_preview_service = build_reference_preview_service(
                app.state.config
            )
        yield

    app = FastAPI(title="CameraAgent Gateway", version="0.3.0", lifespan=lifespan)
    app.state.config = config
    app.state.settings = settings
    app.state.store = InMemorySessionStore()
    app.state.attach_loop = attach_loop
    app.state.shooting_loop = None
    app.state.reference_preview_service = None

    cors_origins = gateway_cfg.get("cors_origins")
    if cors_origins:
        origins = list(cors_origins) if isinstance(cors_origins, list) else ["*"]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(sessions_router)

    if web_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(web_dir / "index.html")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
