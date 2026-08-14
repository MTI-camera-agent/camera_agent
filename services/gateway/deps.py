from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import Header, HTTPException, Request

from services.gateway.reference_preview import ReferencePreviewService
from services.gateway.session_store import InMemorySessionStore
from workflow.shooting_loop import ShootingLoop


@dataclass
class GatewaySettings:
    demo_token: str = ""
    max_frame_long_edge: int = 1280
    frames_dir: Path = Path("outputs/gateway_frames")
    plans_dir: Path = Path("outputs/plans")
    previews_dir: Path = Path("outputs/reference_previews")
    web_dir: Path = Path("frontend/web")


def get_settings(request: Request) -> GatewaySettings:
    return request.app.state.settings


def get_store(request: Request) -> InMemorySessionStore:
    return request.app.state.store


def get_loop(request: Request) -> ShootingLoop:
    loop = getattr(request.app.state, "shooting_loop", None)
    if loop is None:
        raise HTTPException(
            status_code=503,
            detail="ShootingLoop is not configured on this gateway instance",
        )
    return loop


def get_reference_preview_service(request: Request) -> ReferencePreviewService:
    service = getattr(request.app.state, "reference_preview_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="ReferencePreviewService is not configured on this gateway instance",
        )
    return service


def get_config(request: Request) -> dict[str, Any]:
    return request.app.state.config


def require_demo_token(
    request: Request,
    x_demo_token: str | None = Header(default=None, alias="X-Demo-Token"),
) -> None:
    settings: GatewaySettings = request.app.state.settings
    expected = (settings.demo_token or "").strip()
    if not expected:
        return
    if (x_demo_token or "").strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Demo-Token")


LoopFactory = Callable[[], ShootingLoop]
