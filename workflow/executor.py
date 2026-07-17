from __future__ import annotations

from pathlib import Path
from typing import Any

from schemas.action import ActionExecution, ActionStatus
from schemas.state import Artifact, ExecutionState
from tools.base import ExecutionOptions, ToolContext
from workflow.compiler import CompiledAction
from workflow.reporter import NullTrajectoryReporter, TrajectoryReporter


class ToolExecutor:
    def __init__(
        self,
        *,
        output_dir: Path,
        mask_dir: Path,
        services: dict[str, Any] | None = None,
        reporter: TrajectoryReporter | None = None,
        execution_options: ExecutionOptions | None = None,
    ) -> None:
        self._output_dir = output_dir
        self._mask_dir = mask_dir
        self._services = services or {}
        self._reporter = reporter or NullTrajectoryReporter()
        self._execution_options = execution_options or ExecutionOptions()

    def execute(self, actions: list[CompiledAction], state: ExecutionState) -> ExecutionState:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._mask_dir.mkdir(parents=True, exist_ok=True)
        context = ToolContext(
            state=state,
            output_dir=self._output_dir,
            mask_dir=self._mask_dir,
            services=self._services,
            reporter=self._reporter,
            execution_options=self._execution_options,
        )
        total = len(actions)
        for index, compiled in enumerate(actions, start=1):
            action = compiled.action
            self._reporter.tool_started(index=index, total=total, action=action)
            state.history.append(ActionExecution(action=action, status=ActionStatus.RUNNING))
            try:
                result = compiled.tool.run(action, context)
            except Exception as exc:
                state.history[-1] = ActionExecution(
                    action=action,
                    status=ActionStatus.FAILED,
                    message=str(exc),
                )
                self._reporter.tool_failed(index=index, total=total, action=action, error=exc)
                raise
            alias = action.output or action.action
            artifact = Artifact(
                kind=result.artifact_kind,
                path=result.path,
                data=result.data,
                source_action=action.action,
            )
            state.add_artifact(alias, artifact)
            state.history[-1] = ActionExecution(
                action=action,
                status=ActionStatus.SUCCEEDED,
                artifact_id=artifact.id,
                message=result.message,
            )
            self._reporter.tool_finished(
                index=index,
                total=total,
                action=action,
                artifact=artifact,
                alias=alias,
            )
        return state
