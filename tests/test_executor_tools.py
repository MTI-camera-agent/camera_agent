from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops

from schemas.action import ActionSpec
from schemas.plan import GoalSpec, Plan
from tools import create_default_tool_registry
from tools.base import ExecutionOptions
from workflow.compiler import PlanCompiler
from workflow.executor import ToolExecutor
from workflow.reporter import ConsoleTrajectoryReporter
from workflow.state_manager import StateManager


class RecordingImageGenerator:
    def __init__(self) -> None:
        self.generations: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []

    def generate(self, *, prompt: str, output_path: Path, size: str = "1024x1024") -> Path:
        self.generations.append(
            {
                "prompt": prompt,
                "output_path": output_path,
                "size": size,
            }
        )
        _write_test_image(output_path, color=(230, 210, 120))
        return output_path

    def edit(self, *, image_path: Path, prompt: str, output_path: Path, size: str = "auto") -> Path:
        self.edits.append(
            {
                "image_path": image_path,
                "prompt": prompt,
                "output_path": output_path,
                "size": size,
            }
        )
        _write_test_image(output_path)
        return output_path


def _write_test_image(
    path: Path,
    size: tuple[int, int] = (80, 60),
    color: tuple[int, int, int] = (40, 120, 200),
) -> None:
    image = Image.new("RGB", size, color=color)
    image.save(path)


def test_executor_runs_deterministic_and_vision_tools(tmp_path: Path) -> None:
    input_image = tmp_path / "input.png"
    _write_test_image(input_image)
    registry = create_default_tool_registry()
    compiler = PlanCompiler(registry)
    plan = Plan(
        goal=GoalSpec(objective="exercise local tools"),
        steps=[
            ActionSpec(action="image_metadata", output="meta"),
            ActionSpec(action="segment_subject", args={"mode": "center_ellipse"}, output="mask"),
            ActionSpec(action="resize", args={"width": 40, "height": 30}, output="small"),
            ActionSpec(action="blur", args={"radius": 1.0}, output="blurred"),
            ActionSpec(action="sharpen", output="sharp"),
        ],
    )
    state_manager = StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans")
    state = state_manager.initial_state(image_path=input_image, user_prompt="test")
    executor = ToolExecutor(output_dir=tmp_path / "images", mask_dir=tmp_path / "masks")

    result = executor.execute(compiler.compile(plan), state)

    assert result.artifacts["meta"].kind == "metadata"
    assert result.artifacts["mask"].path is not None
    assert result.artifacts["mask"].path.exists()
    assert result.artifacts["sharp"].path is not None
    assert result.artifacts["sharp"].path.exists()
    assert len(result.history) == 5
    with Image.open(result.current_image) as image:
        assert image.size == (40, 30)


def test_executor_resolves_builtin_image_aliases(tmp_path: Path) -> None:
    input_image = tmp_path / "input.png"
    _write_test_image(input_image)
    registry = create_default_tool_registry()
    compiler = PlanCompiler(registry)
    plan = Plan(
        goal=GoalSpec(objective="use planner image aliases"),
        steps=[
            ActionSpec(
                action="segment_subject",
                args={"image": "original_image", "mode": "full"},
                output="subject_mask",
            ),
            ActionSpec(
                action="resize",
                args={"image": "current_image", "width": 32, "height": 32},
                output="small",
            ),
        ],
    )
    state_manager = StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans")
    state = state_manager.initial_state(image_path=input_image, user_prompt="test")
    executor = ToolExecutor(output_dir=tmp_path / "images", mask_dir=tmp_path / "masks")

    result = executor.execute(compiler.compile(plan), state)

    assert result.artifacts["subject_mask"].path is not None
    assert result.artifacts["subject_mask"].path.exists()
    with Image.open(result.current_image) as image:
        assert image.size == (32, 32)


def test_segment_full_mode_is_not_whole_image_mask(tmp_path: Path) -> None:
    input_image = tmp_path / "input.png"
    _write_test_image(input_image)
    registry = create_default_tool_registry()
    compiler = PlanCompiler(registry)
    plan = Plan(
        goal=GoalSpec(objective="create full-subject mask"),
        steps=[
            ActionSpec(
                action="segment_subject",
                args={"image": "original_image", "mode": "full"},
                output="subject_mask",
            )
        ],
    )
    state_manager = StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans")
    state = state_manager.initial_state(image_path=input_image, user_prompt="test")
    executor = ToolExecutor(output_dir=tmp_path / "images", mask_dir=tmp_path / "masks")

    result = executor.execute(compiler.compile(plan), state)

    mask_path = result.artifacts["subject_mask"].path
    assert mask_path is not None
    with Image.open(mask_path) as mask:
        assert mask.convert("L").getextrema() == (0, 255)


def test_manual_full_subject_mask_blend_changes_background(tmp_path: Path) -> None:
    input_image = tmp_path / "input.png"
    _write_test_image(input_image, color=(40, 120, 200))
    generator = RecordingImageGenerator()
    registry = create_default_tool_registry()
    compiler = PlanCompiler(registry)
    plan = Plan(
        goal=GoalSpec(objective="manual blend with full-subject mask"),
        steps=[
            ActionSpec(
                action="segment_subject",
                args={"image": "original_image", "mode": "full"},
                output="subject_mask",
            ),
            ActionSpec(
                action="generate_image",
                args={"prompt": "sunny beach", "size": "1024x1024"},
                output="beach_background",
            ),
            ActionSpec(
                action="blend_subject",
                args={
                    "foreground": "original_image",
                    "background": "beach_background",
                    "mask": "subject_mask",
                    "mask_blur_radius": 0,
                },
                output="composite",
                requires=["subject_mask", "beach_background"],
            ),
        ],
    )
    state_manager = StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans")
    state = state_manager.initial_state(image_path=input_image, user_prompt="test")
    executor = ToolExecutor(
        output_dir=tmp_path / "images",
        mask_dir=tmp_path / "masks",
        services={"image_generator": generator},
    )

    result = executor.execute(compiler.compile(plan), state)

    with Image.open(input_image) as original, Image.open(result.current_image) as composite:
        assert ImageChops.difference(original.convert("RGB"), composite.convert("RGB")).getbbox()


def test_change_pose_tool_uses_focused_prompt(tmp_path: Path) -> None:
    input_image = tmp_path / "input.png"
    _write_test_image(input_image)
    generator = RecordingImageGenerator()
    registry = create_default_tool_registry()
    compiler = PlanCompiler(registry)
    plan = Plan(
        goal=GoalSpec(objective="change pose without adding props"),
        steps=[
            ActionSpec(
                action="change_pose",
                args={
                    "image": "original_image",
                    "target_pose": "sitting on the ground",
                    "preserve_prompt": "Preserve identity and clothing.",
                },
                output="sitting_pose_image",
            )
        ],
    )
    state_manager = StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans")
    state = state_manager.initial_state(image_path=input_image, user_prompt="test")
    executor = ToolExecutor(
        output_dir=tmp_path / "images",
        mask_dir=tmp_path / "masks",
        services={"image_generator": generator},
    )

    result = executor.execute(compiler.compile(plan), state)

    assert result.artifacts["sitting_pose_image"].path is not None
    assert generator.edits
    prompt = str(generator.edits[0]["prompt"])
    assert "Change only the main subject pose" in prompt
    assert "Avoid unrelated changes" in prompt


def test_replace_background_is_composite(tmp_path: Path) -> None:
    input_image = tmp_path / "input.png"
    _write_test_image(input_image)
    generator = RecordingImageGenerator()
    registry = create_default_tool_registry()
    compiler = PlanCompiler(registry)
    plan = Plan(
        goal=GoalSpec(objective="replace background through lower-layer tools"),
        steps=[
            ActionSpec(
                action="replace_background",
                args={
                    "image": "original_image",
                    "background_prompt": "sunny beach",
                    "mask_mode": "center_ellipse",
                    "refine": False,
                },
                output="beach_background_image",
            )
        ],
    )
    state_manager = StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans")
    state = state_manager.initial_state(image_path=input_image, user_prompt="test")
    executor = ToolExecutor(
        output_dir=tmp_path / "images",
        mask_dir=tmp_path / "masks",
        services={"image_generator": generator},
    )

    result = executor.execute(compiler.compile(plan), state)
    artifact = result.artifacts["beach_background_image"]

    assert artifact.path is not None
    assert artifact.path.exists()
    assert artifact.data["substeps"] == [
        "segment_subject",
        "generate_image",
        "blend_subject",
    ]
    assert Path(str(artifact.data["mask_path"])).exists()
    assert Path(str(artifact.data["background_path"])).exists()
    assert generator.generations
    assert not generator.edits


def test_replace_background_normalizes_planner_friendly_args(tmp_path: Path) -> None:
    input_image = tmp_path / "input.png"
    _write_test_image(input_image)
    generator = RecordingImageGenerator()
    registry = create_default_tool_registry()
    compiler = PlanCompiler(registry)
    plan = Plan(
        goal=GoalSpec(objective="replace background with planner-friendly args"),
        steps=[
            ActionSpec(
                action="replace_background",
                args={
                    "image": "original_image",
                    "background_prompt": "sunny beach",
                    "mask_mode": "full",
                    "background_size": "original",
                },
                output="beach_background_image",
            )
        ],
    )
    state_manager = StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans")
    state = state_manager.initial_state(image_path=input_image, user_prompt="test")
    executor = ToolExecutor(
        output_dir=tmp_path / "images",
        mask_dir=tmp_path / "masks",
        services={"image_generator": generator},
    )

    result = executor.execute(compiler.compile(plan), state)
    artifact = result.artifacts["beach_background_image"]

    assert artifact.path is not None
    assert generator.generations[0]["size"] == "1024x1024"
    assert generator.edits
    assert artifact.data["requested_mask_mode"] == "full"
    assert artifact.data["mask_mode"] == "full"
    assert artifact.data["requested_background_size"] == "original"
    assert artifact.data["background_size"] == "1024x1024"
    assert artifact.data["substeps"] == [
        "segment_subject",
        "generate_image",
        "blend_subject",
        "edit_image_refine",
    ]
    assert artifact.data["refine_prompt"]


def test_replace_background_debug_option_disables_refine_only_on_configured_iteration(
    tmp_path: Path,
) -> None:
    input_image = tmp_path / "input.png"
    _write_test_image(input_image)
    generator = RecordingImageGenerator()
    registry = create_default_tool_registry()
    compiler = PlanCompiler(registry)
    plan = Plan(
        goal=GoalSpec(objective="force weak first pass"),
        steps=[
            ActionSpec(
                action="replace_background",
                args={
                    "image": "original_image",
                    "background_prompt": "sunny beach",
                },
                output="beach_background_image",
            )
        ],
    )
    state_manager = StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans")
    state = state_manager.initial_state(image_path=input_image, user_prompt="test")
    state.iteration = 0
    executor = ToolExecutor(
        output_dir=tmp_path / "images",
        mask_dir=tmp_path / "masks",
        services={"image_generator": generator},
        execution_options=ExecutionOptions(
            replace_background_refine_disabled_iterations={0}
        ),
    )

    result = executor.execute(compiler.compile(plan), state)
    artifact = result.artifacts["beach_background_image"]

    assert artifact.data["substeps"] == [
        "segment_subject",
        "generate_image",
        "blend_subject",
    ]
    assert artifact.data["refine_requested"] is True
    assert artifact.data["refine_enabled"] is False
    assert artifact.data["refine_disabled_reason"] == "debug_disable_refine_first_iteration"
    assert not generator.edits


def test_replace_background_debug_option_does_not_disable_other_iterations(
    tmp_path: Path,
) -> None:
    input_image = tmp_path / "input.png"
    _write_test_image(input_image)
    generator = RecordingImageGenerator()
    registry = create_default_tool_registry()
    compiler = PlanCompiler(registry)
    plan = Plan(
        goal=GoalSpec(objective="normal second pass"),
        steps=[
            ActionSpec(
                action="replace_background",
                args={
                    "image": "original_image",
                    "background_prompt": "sunny beach",
                },
                output="beach_background_image",
            )
        ],
    )
    state_manager = StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans")
    state = state_manager.initial_state(image_path=input_image, user_prompt="test")
    state.iteration = 1
    executor = ToolExecutor(
        output_dir=tmp_path / "images",
        mask_dir=tmp_path / "masks",
        services={"image_generator": generator},
        execution_options=ExecutionOptions(
            replace_background_refine_disabled_iterations={0}
        ),
    )

    result = executor.execute(compiler.compile(plan), state)
    artifact = result.artifacts["beach_background_image"]

    assert artifact.data["substeps"] == [
        "segment_subject",
        "generate_image",
        "blend_subject",
        "edit_image_refine",
    ]
    assert artifact.data["refine_enabled"] is True
    assert artifact.data["refine_disabled_reason"] is None
    assert generator.edits


def test_replace_background_reports_composite_substeps(tmp_path: Path, capsys) -> None:
    input_image = tmp_path / "input.png"
    _write_test_image(input_image)
    generator = RecordingImageGenerator()
    registry = create_default_tool_registry()
    compiler = PlanCompiler(registry)
    plan = Plan(
        goal=GoalSpec(objective="trace composite background replacement"),
        steps=[
            ActionSpec(
                action="replace_background",
                args={
                    "image": "original_image",
                    "background_prompt": "sunny beach",
                    "refine": False,
                },
                output="beach_background_image",
            )
        ],
    )
    state_manager = StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans")
    state = state_manager.initial_state(image_path=input_image, user_prompt="test")
    executor = ToolExecutor(
        output_dir=tmp_path / "images",
        mask_dir=tmp_path / "masks",
        services={"image_generator": generator},
        reporter=ConsoleTrajectoryReporter(),
    )

    executor.execute(compiler.compile(plan), state)

    output = capsys.readouterr().out
    assert "substep_1/3: replace_background.segment_subject" in output
    assert "substep_2/3: replace_background.generate_image" in output
    assert "substep_3/3: replace_background.blend_subject" in output


def test_state_manager_round_trips_state(tmp_path: Path) -> None:
    input_image = tmp_path / "input.png"
    _write_test_image(input_image)
    manager = StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans")
    state = manager.initial_state(image_path=input_image, user_prompt="round trip")

    saved = manager.save_state(state)
    loaded = manager.load_state(saved)

    assert loaded.original_image == input_image.resolve()
    assert loaded.user_prompt == "round trip"
