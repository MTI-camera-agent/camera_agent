from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agents.planner import PlannerAgent
from agents.reflector import ReflectorAgent
from schemas.state import ExecutionState
from workflow.compiler import PlanCompiler
from workflow.executor import ToolExecutor
from workflow.history import summarize_state
from workflow.reporter import NullTrajectoryReporter, TrajectoryReporter
from workflow.state_manager import StateManager


@dataclass(frozen=True)
class LoopResult:
    state: ExecutionState
    final_image: Path
    satisfied: bool


class ImageLoop:
    def __init__(
        self,
        *,
        planner: PlannerAgent,
        reflector: ReflectorAgent,
        compiler: PlanCompiler,
        executor: ToolExecutor,
        state_manager: StateManager,
        max_iterations: int = 2,
        reporter: TrajectoryReporter | None = None,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        self._planner = planner
        self._reflector = reflector
        self._compiler = compiler
        self._executor = executor
        self._state_manager = state_manager
        self._max_iterations = max_iterations
        self._reporter = reporter or NullTrajectoryReporter()

    def run(self, *, image_path: Path, user_prompt: str) -> LoopResult:
        state = self._state_manager.initial_state(image_path=image_path, user_prompt=user_prompt)
        self._reporter.run_started(
            image_path=state.original_image,
            user_prompt=user_prompt,
            max_iterations=self._max_iterations,
        )
        feedback: str | None = None
        for iteration in range(self._max_iterations):
            state.iteration = iteration
            self._reporter.iteration_started(iteration=iteration, state=state)
            self._reporter.planning_started(image_path=state.current_image, feedback=feedback)
            plan = self._planner.plan(
                image_path=state.current_image,
                user_prompt=user_prompt,
                state_summary=summarize_state(state),
                feedback=feedback,
            )
            plan_path = self._state_manager.save_plan(plan, iteration)
            self._reporter.plan_created(plan=plan, plan_path=plan_path)
            self._reporter.compilation_started(plan=plan)
            compiled = self._compiler.compile(plan)
            self._reporter.compilation_finished(actions=compiled)
            state = self._executor.execute(compiled, state)
            self._reporter.evaluation_started(
                original_image=state.original_image,
                current_image=state.current_image,
            )
            report = self._reflector.evaluate(
                original_image=state.original_image,
                current_image=state.current_image,
                user_prompt=user_prompt,
                state_summary=summarize_state(state),
            )
            state.evaluations.append(report)
            state_path = self._state_manager.save_state(state)
            self._reporter.evaluation_finished(report=report, state_path=state_path)
            if report.satisfied:
                self._reporter.run_finished(final_image=state.current_image, satisfied=True)
                return LoopResult(state=state, final_image=state.current_image, satisfied=True)
            feedback = "; ".join(report.missing + report.suggestions) or report.summary
        self._reporter.run_finished(final_image=state.current_image, satisfied=False)
        return LoopResult(state=state, final_image=state.current_image, satisfied=False)
