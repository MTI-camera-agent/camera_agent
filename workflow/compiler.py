from __future__ import annotations

from dataclasses import dataclass

from schemas.action import ActionSpec
from schemas.plan import Plan
from tools.base import ImageTool
from tools.registry import ToolRegistry


@dataclass(frozen=True)
class CompiledAction:
    action: ActionSpec
    tool: ImageTool


class PlanCompiler:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def compile(self, plan: Plan) -> list[CompiledAction]:
        known_outputs: set[str] = set()
        compiled: list[CompiledAction] = []
        for index, action in enumerate(plan.steps):
            tool = self._registry.get(action.action)
            self._validate_required_params(action, tool, index)
            missing_dependencies = [name for name in action.requires if name not in known_outputs]
            if missing_dependencies:
                joined = ", ".join(missing_dependencies)
                raise ValueError(f"Step {index} has unknown dependencies: {joined}")
            compiled.append(CompiledAction(action=action, tool=tool))
            if action.output:
                known_outputs.add(action.output)
        return compiled

    @staticmethod
    def _validate_required_params(action: ActionSpec, tool: ImageTool, index: int) -> None:
        required = tool.spec.required_parameters
        missing = sorted(required - set(action.args))
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Step {index} action {action.action!r} missing required args: {joined}")
