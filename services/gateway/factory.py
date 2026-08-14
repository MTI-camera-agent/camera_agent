from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.intent_agent import IntentAgent
from agents.prompt_loader import PromptLoader
from agents.shooting_planner_agent import ShootingPlannerAgent
from models import build_structured_vision_client
from skills.qwen3vl_photo import Qwen3VLPhotoClient
from utils.file import ensure_dir
from workflow.shooting_loop import ShootingLoop


def build_shooting_loop(config: dict[str, Any]) -> ShootingLoop:
    """Instantiate ShootingLoop from root config (provider-neutral factories only)."""
    shooting_cfg = config.get("shooting") or {}
    agent_cfg = dict(shooting_cfg.get("main_agent") or config["structured_vision"])
    agent_cfg.pop("vision_bridge", None)

    vlm_cfg = shooting_cfg.get("qwen3vl") or (
        (config.get("structured_vision") or {}).get("vision_bridge") or {}
    )
    if not vlm_cfg.get("base_url"):
        raise RuntimeError(
            "shooting.qwen3vl.base_url (or structured_vision.vision_bridge.base_url) "
            "is required for the gateway ShootingLoop"
        )

    prompt_loader = PromptLoader(Path(config.get("prompts_dir", "prompts")))
    agent_client = build_structured_vision_client(agent_cfg)
    photo_vlm = Qwen3VLPhotoClient(vlm_cfg)
    output_root = Path(config.get("outputs_dir", "outputs"))
    plan_dir = ensure_dir(output_root / "plans")

    return ShootingLoop(
        photo_vlm=photo_vlm,
        intent_agent=IntentAgent(agent_client, prompt_loader),
        planner_agent=ShootingPlannerAgent(agent_client, prompt_loader),
        plan_dir=plan_dir,
    )


def build_reference_preview_service(config: dict[str, Any]):
    """Build ReferencePreviewService from root config (HTTP clients only, no GPU)."""
    from models.factory import build_image_generator
    from services.gateway.reference_preview import ReferencePreviewService
    from skills.reference_image import ReferenceImageSkill

    image_cfg = config.get("image_generator") or {}
    if not image_cfg:
        raise RuntimeError("image_generator config is required for reference preview")
    primary = ReferenceImageSkill(
        client=build_image_generator(image_cfg),
        generator="qwen2511",
    )

    shooting_cfg = config.get("shooting") or {}
    rp_cfg = shooting_cfg.get("reference_preview") or {}
    fallback = None
    if rp_cfg.get("fallback_generator"):
        fb_cfg = config.get("image_generator_fallback")
        if fb_cfg:
            fallback = ReferenceImageSkill(
                client=build_image_generator(fb_cfg),
                generator="flux",
            )

    gateway_cfg = config.get("gateway") or {}
    output_root = Path(config.get("outputs_dir", "outputs"))
    previews_dir = Path(gateway_cfg.get("previews_dir") or (output_root / "reference_previews"))
    poll_interval = float(rp_cfg.get("poll_interval_seconds", 1.5))
    return ReferencePreviewService(
        previews_dir=previews_dir,
        primary=primary,
        fallback=fallback,
        poll_interval_seconds=poll_interval,
    )
