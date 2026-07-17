from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from schemas.action import ActionSpec
from schemas.plan import Plan
from schemas.state import Artifact, EvaluationReport, ExecutionState
from workflow.compiler import CompiledAction


class TrajectoryReporter(Protocol):
    def run_started(self, *, image_path: Path, user_prompt: str, max_iterations: int) -> None:
        ...

    def iteration_started(self, *, iteration: int, state: ExecutionState) -> None:
        ...

    def planning_started(self, *, image_path: Path, feedback: str | None) -> None:
        ...

    def plan_created(self, *, plan: Plan, plan_path: Path) -> None:
        ...

    def compilation_started(self, *, plan: Plan) -> None:
        ...

    def compilation_finished(self, *, actions: list[CompiledAction]) -> None:
        ...

    def tool_started(self, *, index: int, total: int, action: ActionSpec) -> None:
        ...

    def tool_finished(
        self,
        *,
        index: int,
        total: int,
        action: ActionSpec,
        artifact: Artifact,
        alias: str,
    ) -> None:
        ...

    def tool_failed(self, *, index: int, total: int, action: ActionSpec, error: Exception) -> None:
        ...

    def composite_substep_started(
        self,
        *,
        parent_action: str,
        index: int,
        total: int,
        action: ActionSpec,
    ) -> None:
        ...

    def composite_substep_finished(
        self,
        *,
        parent_action: str,
        index: int,
        total: int,
        action: ActionSpec,
        artifact_kind: str,
        artifact_path: Path | None,
        data: dict[str, Any],
    ) -> None:
        ...

    def composite_substep_failed(
        self,
        *,
        parent_action: str,
        index: int,
        total: int,
        action: ActionSpec,
        error: Exception,
    ) -> None:
        ...

    def evaluation_started(self, *, original_image: Path, current_image: Path) -> None:
        ...

    def evaluation_finished(self, *, report: EvaluationReport, state_path: Path) -> None:
        ...

    def run_finished(self, *, final_image: Path, satisfied: bool) -> None:
        ...


class NullTrajectoryReporter:
    def run_started(self, *, image_path: Path, user_prompt: str, max_iterations: int) -> None:
        pass

    def iteration_started(self, *, iteration: int, state: ExecutionState) -> None:
        pass

    def planning_started(self, *, image_path: Path, feedback: str | None) -> None:
        pass

    def plan_created(self, *, plan: Plan, plan_path: Path) -> None:
        pass

    def compilation_started(self, *, plan: Plan) -> None:
        pass

    def compilation_finished(self, *, actions: list[CompiledAction]) -> None:
        pass

    def tool_started(self, *, index: int, total: int, action: ActionSpec) -> None:
        pass

    def tool_finished(
        self,
        *,
        index: int,
        total: int,
        action: ActionSpec,
        artifact: Artifact,
        alias: str,
    ) -> None:
        pass

    def tool_failed(self, *, index: int, total: int, action: ActionSpec, error: Exception) -> None:
        pass

    def composite_substep_started(
        self,
        *,
        parent_action: str,
        index: int,
        total: int,
        action: ActionSpec,
    ) -> None:
        pass

    def composite_substep_finished(
        self,
        *,
        parent_action: str,
        index: int,
        total: int,
        action: ActionSpec,
        artifact_kind: str,
        artifact_path: Path | None,
        data: dict[str, Any],
    ) -> None:
        pass

    def composite_substep_failed(
        self,
        *,
        parent_action: str,
        index: int,
        total: int,
        action: ActionSpec,
        error: Exception,
    ) -> None:
        pass

    def evaluation_started(self, *, original_image: Path, current_image: Path) -> None:
        pass

    def evaluation_finished(self, *, report: EvaluationReport, state_path: Path) -> None:
        pass

    def run_finished(self, *, final_image: Path, satisfied: bool) -> None:
        pass


class JsonTrajectoryReporter:
    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        record = {
            "time": datetime.now(UTC).isoformat(),
            "event": event,
            **payload,
        }
        print(json.dumps(record, default=str, ensure_ascii=True), flush=True)

    def run_started(self, *, image_path: Path, user_prompt: str, max_iterations: int) -> None:
        self._emit(
            "run_started",
            {
                "image_path": image_path,
                "user_prompt": user_prompt,
                "max_iterations": max_iterations,
            },
        )

    def iteration_started(self, *, iteration: int, state: ExecutionState) -> None:
        self._emit(
            "iteration_started",
            {
                "iteration": iteration,
                "current_image": state.current_image,
                "artifact_count": len(state.artifacts),
            },
        )

    def planning_started(self, *, image_path: Path, feedback: str | None) -> None:
        self._emit("planning_started", {"image_path": image_path, "feedback": feedback})

    def plan_created(self, *, plan: Plan, plan_path: Path) -> None:
        self._emit("plan_created", {"plan_path": plan_path, "plan": plan.model_dump()})

    def compilation_started(self, *, plan: Plan) -> None:
        self._emit("compilation_started", {"step_count": len(plan.steps)})

    def compilation_finished(self, *, actions: list[CompiledAction]) -> None:
        self._emit(
            "compilation_finished",
            {
                "actions": [
                    {"action": item.action.model_dump(), "tool": item.tool.spec.model_dump()}
                    for item in actions
                ]
            },
        )

    def tool_started(self, *, index: int, total: int, action: ActionSpec) -> None:
        self._emit(
            "tool_started",
            {"index": index, "total": total, "action": action.model_dump()},
        )

    def tool_finished(
        self,
        *,
        index: int,
        total: int,
        action: ActionSpec,
        artifact: Artifact,
        alias: str,
    ) -> None:
        self._emit(
            "tool_finished",
            {
                "index": index,
                "total": total,
                "action": action.action,
                "alias": alias,
                "artifact": artifact.model_dump(),
            },
        )

    def tool_failed(self, *, index: int, total: int, action: ActionSpec, error: Exception) -> None:
        self._emit(
            "tool_failed",
            {
                "index": index,
                "total": total,
                "action": action.model_dump(),
                "error": str(error),
            },
        )

    def composite_substep_started(
        self,
        *,
        parent_action: str,
        index: int,
        total: int,
        action: ActionSpec,
    ) -> None:
        self._emit(
            "composite_substep_started",
            {
                "parent_action": parent_action,
                "index": index,
                "total": total,
                "action": action.model_dump(),
            },
        )

    def composite_substep_finished(
        self,
        *,
        parent_action: str,
        index: int,
        total: int,
        action: ActionSpec,
        artifact_kind: str,
        artifact_path: Path | None,
        data: dict[str, Any],
    ) -> None:
        self._emit(
            "composite_substep_finished",
            {
                "parent_action": parent_action,
                "index": index,
                "total": total,
                "action": action.action,
                "output": action.output,
                "artifact_kind": artifact_kind,
                "artifact_path": artifact_path,
                "data": data,
            },
        )

    def composite_substep_failed(
        self,
        *,
        parent_action: str,
        index: int,
        total: int,
        action: ActionSpec,
        error: Exception,
    ) -> None:
        self._emit(
            "composite_substep_failed",
            {
                "parent_action": parent_action,
                "index": index,
                "total": total,
                "action": action.model_dump(),
                "error": str(error),
            },
        )

    def evaluation_started(self, *, original_image: Path, current_image: Path) -> None:
        self._emit(
            "evaluation_started",
            {"original_image": original_image, "current_image": current_image},
        )

    def evaluation_finished(self, *, report: EvaluationReport, state_path: Path) -> None:
        self._emit(
            "evaluation_finished",
            {"state_path": state_path, "report": report.model_dump()},
        )

    def run_finished(self, *, final_image: Path, satisfied: bool) -> None:
        self._emit("run_finished", {"final_image": final_image, "satisfied": satisfied})


class ConsoleTrajectoryReporter:
    def __init__(self, *, show_json_args: bool = True) -> None:
        self._show_json_args = show_json_args

    def run_started(self, *, image_path: Path, user_prompt: str, max_iterations: int) -> None:
        self._section("Run")
        self._line("input_image", str(image_path))
        self._line("prompt", user_prompt)
        self._line("max_iterations", str(max_iterations))

    def iteration_started(self, *, iteration: int, state: ExecutionState) -> None:
        self._section(f"Iteration {iteration}")
        self._line("current_image", str(state.current_image))
        self._line("known_artifacts", str(len(state.artifacts)))

    def planning_started(self, *, image_path: Path, feedback: str | None) -> None:
        self._subsection("Planning")
        self._line("planner_input_image", str(image_path))
        if feedback:
            self._line("replan_feedback", feedback)

    def plan_created(self, *, plan: Plan, plan_path: Path) -> None:
        self._line("plan_file", str(plan_path))
        self._line("goal", plan.goal.objective)
        if plan.goal.success_criteria:
            self._bullets("success_criteria", plan.goal.success_criteria)
        if plan.assumptions:
            self._bullets("assumptions", plan.assumptions)
        if plan.constraints:
            self._bullets("constraints", plan.constraints)
        if plan.notes:
            self._line("planner_notes", plan.notes)
        self._line("steps", str(len(plan.steps)))
        for index, step in enumerate(plan.steps, start=1):
            self._action_line(index, step)

    def compilation_started(self, *, plan: Plan) -> None:
        self._subsection("Compilation")
        self._line("candidate_steps", str(len(plan.steps)))

    def compilation_finished(self, *, actions: list[CompiledAction]) -> None:
        self._line("compiled_steps", str(len(actions)))
        for index, item in enumerate(actions, start=1):
            self._line(f"step_{index}_tool", item.tool.spec.name)

    def tool_started(self, *, index: int, total: int, action: ActionSpec) -> None:
        self._subsection(f"Execution {index}/{total}")
        self._line("tool_call", action.action)
        if action.requires:
            self._line("requires", ", ".join(action.requires))
        if action.output:
            self._line("output_alias", action.output)
        if action.description:
            self._line("description", action.description)
        self._line("args", self._format_args(action.args))

    def tool_finished(
        self,
        *,
        index: int,
        total: int,
        action: ActionSpec,
        artifact: Artifact,
        alias: str,
    ) -> None:
        self._line("status", "succeeded")
        self._line("artifact_alias", alias)
        self._line("artifact_kind", artifact.kind)
        if artifact.path is not None:
            self._line("artifact_path", str(artifact.path))
        if artifact.data:
            self._line("artifact_data", self._format_args(artifact.data))

    def tool_failed(self, *, index: int, total: int, action: ActionSpec, error: Exception) -> None:
        self._line("status", "failed")
        self._line("error", str(error))

    def composite_substep_started(
        self,
        *,
        parent_action: str,
        index: int,
        total: int,
        action: ActionSpec,
    ) -> None:
        self._line(f"substep_{index}/{total}", f"{parent_action}.{action.action}")
        if action.output:
            self._line("  output_alias", action.output)
        self._line("  args", self._format_args(action.args))

    def composite_substep_finished(
        self,
        *,
        parent_action: str,
        index: int,
        total: int,
        action: ActionSpec,
        artifact_kind: str,
        artifact_path: Path | None,
        data: dict[str, Any],
    ) -> None:
        self._line("  status", "succeeded")
        self._line("  artifact_kind", artifact_kind)
        if artifact_path is not None:
            self._line("  artifact_path", str(artifact_path))
        if data:
            self._line("  artifact_data", self._format_args(data))

    def composite_substep_failed(
        self,
        *,
        parent_action: str,
        index: int,
        total: int,
        action: ActionSpec,
        error: Exception,
    ) -> None:
        self._line("  status", "failed")
        self._line("  error", str(error))

    def evaluation_started(self, *, original_image: Path, current_image: Path) -> None:
        self._subsection("Evaluation")
        self._line("original_image", str(original_image))
        self._line("current_image", str(current_image))

    def evaluation_finished(self, *, report: EvaluationReport, state_path: Path) -> None:
        self._line("state_file", str(state_path))
        self._line("satisfied", str(report.satisfied))
        self._line("score", f"{report.score:.2f}")
        self._line("summary", report.summary)
        if report.missing:
            self._bullets("missing", report.missing)
        if report.suggestions:
            self._bullets("suggestions", report.suggestions)

    def run_finished(self, *, final_image: Path, satisfied: bool) -> None:
        self._section("Final")
        self._line("final_image", str(final_image))
        self._line("satisfied", str(satisfied))

    @staticmethod
    def _section(title: str) -> None:
        print(f"\n== {title} ==", flush=True)

    @staticmethod
    def _subsection(title: str) -> None:
        print(f"\n-- {title} --", flush=True)

    @staticmethod
    def _line(label: str, value: str) -> None:
        print(f"{label}: {value}", flush=True)

    @staticmethod
    def _bullets(label: str, items: list[str]) -> None:
        print(f"{label}:", flush=True)
        for item in items:
            print(f"  - {item}", flush=True)

    def _action_line(self, index: int, action: ActionSpec) -> None:
        bits = [f"{index}. {action.action}"]
        if action.output:
            bits.append(f"-> {action.output}")
        if action.requires:
            bits.append(f"requires={action.requires}")
        if action.description:
            bits.append(f"- {action.description}")
        print(" ".join(bits), flush=True)
        print(f"   args: {self._format_args(action.args)}", flush=True)

    def _format_args(self, value: dict[str, Any]) -> str:
        if not self._show_json_args:
            return str(value)
        return json.dumps(value, ensure_ascii=True, default=str)


def build_trajectory_reporter(trace_format: str) -> TrajectoryReporter:
    if trace_format == "plain":
        return ConsoleTrajectoryReporter()
    if trace_format == "json":
        return JsonTrajectoryReporter()
    if trace_format == "none":
        return NullTrajectoryReporter()
    raise ValueError(f"Unsupported trace format: {trace_format}")
