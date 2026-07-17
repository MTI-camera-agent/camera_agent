from __future__ import annotations

import pytest

from schemas.action import ActionSpec
from schemas.plan import GoalSpec, Plan
from tools import create_default_tool_registry
from workflow.compiler import PlanCompiler


def test_default_registry_exposes_expected_layers() -> None:
    registry = create_default_tool_registry()

    assert {
        "resize",
        "crop",
        "rotate",
        "blur",
        "sharpen",
        "blend_subject",
        "segment_subject",
        "image_metadata",
        "generate_image",
        "change_pose",
        "edit_image",
        "replace_background",
    }.issubset(registry.names())
    assert "replace_background" in registry.specs_markdown()


def test_compiler_validates_required_parameters() -> None:
    registry = create_default_tool_registry()
    compiler = PlanCompiler(registry)
    plan = Plan(
        goal=GoalSpec(objective="resize image"),
        steps=[ActionSpec(action="resize", args={"width": 64}, output="small")],
    )

    with pytest.raises(ValueError, match="height"):
        compiler.compile(plan)


def test_compiler_accepts_dependency_order() -> None:
    registry = create_default_tool_registry()
    compiler = PlanCompiler(registry)
    plan = Plan(
        goal=GoalSpec(objective="mask then resize"),
        steps=[
            ActionSpec(action="segment_subject", args={"mode": "full"}, output="mask"),
            ActionSpec(
                action="resize",
                args={"width": 64, "height": 64},
                output="small",
                requires=["mask"],
            ),
        ],
    )

    compiled = compiler.compile(plan)

    assert [item.action.action for item in compiled] == ["segment_subject", "resize"]
