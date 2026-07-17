from __future__ import annotations

import json
from pathlib import Path

from schemas.action import ActionSpec
from schemas.plan import GoalSpec, Plan
from schemas.state import Artifact, EvaluationReport, ExecutionState
from workflow.reporter import ConsoleTrajectoryReporter, JsonTrajectoryReporter


def test_console_reporter_prints_plan_and_tool_events(capsys) -> None:
    reporter = ConsoleTrajectoryReporter()
    state = ExecutionState(
        original_image=Path("input.png"),
        current_image=Path("input.png"),
        user_prompt="resize",
    )
    plan = Plan(
        goal=GoalSpec(objective="resize image", success_criteria=["64x64 output"]),
        assumptions=["deterministic resize is sufficient"],
        steps=[
            ActionSpec(
                action="resize",
                args={"width": 64, "height": 64},
                output="resized",
            )
        ],
        notes="Use deterministic resizing.",
    )
    action = plan.steps[0]

    reporter.run_started(image_path=Path("input.png"), user_prompt="resize", max_iterations=1)
    reporter.iteration_started(iteration=0, state=state)
    reporter.plan_created(plan=plan, plan_path=Path("plan.json"))
    reporter.tool_started(index=1, total=1, action=action)
    reporter.tool_finished(
        index=1,
        total=1,
        action=action,
        alias="resized",
        artifact=Artifact(kind="image", path=Path("resized.png")),
    )
    reporter.evaluation_finished(
        report=EvaluationReport(satisfied=True, score=1.0, summary="Done."),
        state_path=Path("state.json"),
    )

    output = capsys.readouterr().out

    assert "== Run ==" in output
    assert "goal: resize image" in output
    assert "tool_call: resize" in output
    assert "artifact_path: resized.png" in output
    assert "summary: Done." in output


def test_json_reporter_emits_json_lines(capsys) -> None:
    reporter = JsonTrajectoryReporter()

    reporter.run_finished(final_image=Path("final.png"), satisfied=True)

    line = capsys.readouterr().out.strip()
    payload = json.loads(line)
    assert payload["event"] == "run_finished"
    assert payload["final_image"] == "final.png"
    assert payload["satisfied"] is True
