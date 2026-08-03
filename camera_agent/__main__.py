"""Command-line entry point for the camera agent harness."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .adapters import GeminiReasoner, HttpImageEditor
from .config import DEFAULT_MODEL, ChangeDetectionConfig, HarnessConfig
from .replay import replay_manifest
from .server import run_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--editor-url", default="http://127.0.0.1:8000/edit")
    parser.add_argument("--editor-timeout", type=float, default=180.0)
    parser.add_argument("--max-output-tokens", type=int, default=1200)
    parser.add_argument("--debug-artifacts", type=Path)
    tuning = parser.add_argument_group("clear-change detection tuning")
    defaults = ChangeDetectionConfig()
    tuning.add_argument(
        "--zoom-relative-delta",
        type=float,
        default=defaults.zoom_relative_delta,
    )
    tuning.add_argument(
        "--focus-point-distance",
        type=float,
        default=defaults.focus_point_distance,
    )
    tuning.add_argument(
        "--exposure-point-distance",
        type=float,
        default=defaults.exposure_point_distance,
    )
    tuning.add_argument(
        "--exposure-bias-delta-ev",
        type=float,
        default=defaults.exposure_bias_delta_ev,
    )
    tuning.add_argument(
        "--crop-aspect-ratio-delta",
        type=float,
        default=defaults.crop_aspect_ratio_delta,
    )
    tuning.add_argument(
        "--attitude-delta-degrees",
        type=float,
        default=defaults.attitude_delta_degrees,
    )
    tuning.add_argument(
        "--visual-global-mae",
        type=float,
        default=defaults.visual_global_mae,
    )
    tuning.add_argument(
        "--visual-block-mae",
        type=float,
        default=defaults.visual_block_mae,
    )
    tuning.add_argument(
        "--visual-hash-distance",
        type=int,
        default=defaults.visual_hash_distance,
    )
    tuning.add_argument(
        "--visual-thumbnail-size",
        type=int,
        default=defaults.visual_thumbnail_size,
    )
    tuning.add_argument(
        "--visual-blur-radius",
        type=float,
        default=defaults.visual_blur_radius,
    )
    tuning.add_argument(
        "--visual-alignment-radius",
        type=int,
        default=defaults.visual_alignment_radius,
    )
    tuning.add_argument(
        "--routine-change-confirmations",
        type=int,
        default=defaults.routine_change_confirmations,
        help="Similar changed frames required before VLM analysis (default: %(default)s).",
    )
    tuning.add_argument(
        "--inference-stale-global-mae",
        type=float,
        default=defaults.inference_stale_global_mae,
        help="Whole-frame change that invalidates an in-flight result.",
    )
    tuning.add_argument(
        "--inference-stale-block-mae",
        type=float,
        default=defaults.inference_stale_block_mae,
        help="Local change that invalidates an in-flight result.",
    )
    parser.add_argument(
        "--replay",
        type=Path,
        help="Replay a JSONL observation manifest without opening a listener.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> HarnessConfig:
    return HarnessConfig(
        host=args.host,
        port=args.port,
        model=args.model,
        editor_url=args.editor_url,
        editor_timeout_seconds=args.editor_timeout,
        max_output_tokens=args.max_output_tokens,
        debug_artifacts=args.debug_artifacts,
        change_detection=ChangeDetectionConfig(
            zoom_relative_delta=args.zoom_relative_delta,
            focus_point_distance=args.focus_point_distance,
            exposure_point_distance=args.exposure_point_distance,
            exposure_bias_delta_ev=args.exposure_bias_delta_ev,
            crop_aspect_ratio_delta=args.crop_aspect_ratio_delta,
            attitude_delta_degrees=args.attitude_delta_degrees,
            visual_global_mae=args.visual_global_mae,
            visual_block_mae=args.visual_block_mae,
            visual_hash_distance=args.visual_hash_distance,
            visual_thumbnail_size=args.visual_thumbnail_size,
            visual_blur_radius=args.visual_blur_radius,
            visual_alignment_radius=args.visual_alignment_radius,
            routine_change_confirmations=args.routine_change_confirmations,
            inference_stale_global_mae=args.inference_stale_global_mae,
            inference_stale_block_mae=args.inference_stale_block_mae,
        ),
    )


async def async_main(args: argparse.Namespace) -> None:
    config = config_from_args(args)
    reasoner = GeminiReasoner(
        model=config.model,
        max_output_tokens=config.max_output_tokens,
    )
    if args.replay:
        await replay_manifest(args.replay, reasoner, config)
        return
    editor = HttpImageEditor(
        config.editor_url,
        timeout_seconds=config.editor_timeout_seconds,
    )
    await run_server(reasoner, editor, config)


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        logging.getLogger("camera_agent").info("Stopped")


if __name__ == "__main__":
    main()
