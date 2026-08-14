#!/usr/bin/env python3
"""CLI for MVP P1 shooting slow path (Question → ShootingPlan).

Qwen3-VL provides scene facts + aesthetic draft (no userIntent in aesthetic call).
Main Agent reconciles conflicts into Questions and the final editInstruction.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.intent_agent import IntentAgent
from agents.prompt_loader import PromptLoader
from agents.shooting_planner_agent import ShootingPlannerAgent
from models import build_structured_vision_client
from schemas.shooting import IntentAnswer
from skills.qwen3vl_photo import Qwen3VLPhotoClient
from utils import load_config
from utils.file import ensure_dir
from utils.logger import configure_logging
from workflow.shooting_loop import ShootingLoop


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument(
        "--image",
        type=Path,
        default=Path("test_img/02-input_frame.jpg"),
        help="Preview frame (default:断桥样例)",
    )
    parser.add_argument(
        "--prompt",
        default="在断桥拍游客照，湖面和远山，人物在右侧",
        help="User shooting intent text",
    )
    parser.add_argument(
        "--answers",
        default="",
        help=(
            "JSON list of {questionId,value} to skip interactive confirm. "
            "Example: '[{\"questionId\":\"q1\",\"value\":\"全身\"}]'"
        ),
    )
    return parser


def _interactive_answers(questions: list) -> list[IntentAnswer]:
    answers: list[IntentAnswer] = []
    for question in questions:
        print(f"\nQ [{question.question_id}]: {question.text}")
        if question.options:
            print("options: " + " | ".join(question.options))
        value = input("answer> ").strip()
        if not value:
            raise SystemExit("Empty answer; aborting.")
        answers.append(
            IntentAnswer(question_id=question.question_id, value=value)
        )
    return answers


def _parse_answers(raw: str) -> list[IntentAnswer]:
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise ValueError("--answers must be a non-empty JSON list")
    return [IntentAnswer.model_validate(item) for item in data]


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    logging_cfg = config.get("logging")
    if isinstance(logging_cfg, dict):
        configure_logging(config=logging_cfg)
    else:
        configure_logging(str(logging_cfg or "INFO"))

    image_path = args.image.resolve()
    if not image_path.is_file():
        print(f"ERROR: image not found: {image_path}", file=sys.stderr)
        return 1

    shooting_cfg = config.get("shooting") or {}
    agent_cfg = shooting_cfg.get("main_agent") or config["structured_vision"]
    # Shooting agents are text-only over Qwen evidence — drop vision_bridge to avoid
    # accidental image calls on DeepSeek path.
    agent_cfg = dict(agent_cfg)
    agent_cfg.pop("vision_bridge", None)

    vlm_cfg = shooting_cfg.get("qwen3vl") or (
        (config.get("structured_vision") or {}).get("vision_bridge") or {}
    )
    if not vlm_cfg.get("base_url"):
        print(
            "ERROR: shooting.qwen3vl.base_url (or structured_vision.vision_bridge) required",
            file=sys.stderr,
        )
        return 1

    prompt_loader = PromptLoader(Path(config.get("prompts_dir", "prompts")))
    agent_client = build_structured_vision_client(agent_cfg)
    photo_vlm = Qwen3VLPhotoClient(vlm_cfg)
    output_root = Path(config.get("outputs_dir", "outputs"))
    plan_dir = ensure_dir(output_root / "plans")

    loop = ShootingLoop(
        photo_vlm=photo_vlm,
        intent_agent=IntentAgent(agent_client, prompt_loader),
        planner_agent=ShootingPlannerAgent(agent_client, prompt_loader),
        plan_dir=plan_dir,
    )

    print("== Shooting P1: Qwen scene + aesthetic draft ==")
    print(f"image: {image_path}")
    print(f"intent: {args.prompt}")
    intent_phase = loop.collect_intent_phase(
        image_path=image_path, user_intent=args.prompt
    )
    print("\n-- Scene facts --")
    print(intent_phase.scene_facts.narrative)
    print("\n-- Aesthetic draft (no userIntent) --")
    print(intent_phase.aesthetic_draft.instruction)
    print(f"\n-- draftGoal --\n{intent_phase.draft_goal}")
    if intent_phase.conflicts:
        print("\n-- Conflicts --")
        for conflict in intent_phase.conflicts:
            print(f"- {conflict.summary}")
    print("\n-- Questions --")
    for question in intent_phase.questions:
        print(f"[{question.question_id}] {question.text}")
        if question.options:
            print("  options:", ", ".join(question.options))

    if args.answers.strip():
        answers = _parse_answers(args.answers)
    else:
        answers = _interactive_answers(intent_phase.questions)

    result = loop.confirm_and_plan(
        user_intent=args.prompt,
        intent_phase=intent_phase,
        answers=answers,
    )
    print("\n== PlanAndEditInstruction ==")
    print(f"plan_file: {result.plan_path}")
    print(f"goal: {result.plan_bundle.shooting_plan.goal}")
    print(f"editInstruction: {result.plan_bundle.edit_instruction}")
    print(f"intentResolutionNotes: {result.plan_bundle.intent_resolution_notes}")
    print(f"coarseGuidance: {result.plan_bundle.coarse_guidance.advice_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
