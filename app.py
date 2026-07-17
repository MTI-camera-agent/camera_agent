from __future__ import annotations

import argparse
from pathlib import Path

from agents import PlannerAgent, ReflectorAgent
from agents.prompt_loader import PromptLoader
from models import build_image_generator, build_structured_vision_client
from tools import create_default_tool_registry
from tools.base import ExecutionOptions
from utils import load_config
from utils.file import ensure_dir
from utils.logger import configure_logging
from workflow import ImageLoop, PlanCompiler, StateManager, ToolExecutor, build_trajectory_reporter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Camera imagery agent prototype.")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument(
        "--trace-format",
        choices=["plain", "json", "none"],
        default=None,
        help="Structured trajectory output format. Defaults to config tracing.format.",
    )
    parser.add_argument(
        "--debug-disable-refine-first-iteration",
        action="store_true",
        help=(
            "Debug trajectory mode: disable replace_background's final refinement substep "
            "only on iteration 0 so replanning behavior can be exercised."
        ),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    configure_logging(str(config.get("logging", {}).get("level", "INFO")))

    registry = create_default_tool_registry()
    prompt_loader = PromptLoader(Path(config.get("prompts_dir", "prompts")))
    vision_client = build_structured_vision_client(config["structured_vision"])
    image_generator = build_image_generator(config["image_generator"])

    output_root = Path(config.get("outputs_dir", "outputs"))
    output_dirs = {
        "images": ensure_dir(output_root / "images"),
        "masks": ensure_dir(output_root / "masks"),
        "logs": ensure_dir(output_root / "logs"),
        "plans": ensure_dir(output_root / "plans"),
    }
    trace_format = args.trace_format or str(config.get("tracing", {}).get("format", "plain"))
    reporter = build_trajectory_reporter(trace_format)
    execution_options = ExecutionOptions(
        replace_background_refine_disabled_iterations={0}
        if args.debug_disable_refine_first_iteration
        else set()
    )

    planner = PlannerAgent(
        client=vision_client,
        prompt_loader=prompt_loader,
        tool_catalog=registry.specs_markdown(),
    )
    reflector = ReflectorAgent(client=vision_client, prompt_loader=prompt_loader)
    loop = ImageLoop(
        planner=planner,
        reflector=reflector,
        compiler=PlanCompiler(registry),
        executor=ToolExecutor(
            output_dir=output_dirs["images"],
            mask_dir=output_dirs["masks"],
            services={"image_generator": image_generator},
            reporter=reporter,
            execution_options=execution_options,
        ),
        state_manager=StateManager(log_dir=output_dirs["logs"], plan_dir=output_dirs["plans"]),
        max_iterations=args.max_iterations or int(config.get("loop", {}).get("max_iterations", 2)),
        reporter=reporter,
    )

    result = loop.run(image_path=args.image, user_prompt=args.prompt)
    if trace_format == "none":
        print(f"final_image={result.final_image}")
        print(f"satisfied={result.satisfied}")
        if result.state.evaluations:
            print(f"evaluation={result.state.evaluations[-1].summary}")


if __name__ == "__main__":
    main()
