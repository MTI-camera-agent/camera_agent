from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter

from schemas.plan import Plan
from schemas.state import ExecutionState


class StateManager:
    def __init__(self, *, log_dir: Path, plan_dir: Path) -> None:
        self._log_dir = log_dir
        self._plan_dir = plan_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._plan_dir.mkdir(parents=True, exist_ok=True)

    def initial_state(self, *, image_path: Path, user_prompt: str) -> ExecutionState:
        resolved = image_path.expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Input image does not exist: {resolved}")
        return ExecutionState(
            original_image=resolved,
            current_image=resolved,
            user_prompt=user_prompt,
        )

    def save_state(self, state: ExecutionState) -> Path:
        path = self._log_dir / f"state_iter_{state.iteration:02d}.json"
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        return path

    def save_plan(self, plan: Plan, iteration: int) -> Path:
        path = self._plan_dir / f"plan_iter_{iteration:02d}.json"
        path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_state(self, path: Path) -> ExecutionState:
        adapter = TypeAdapter(ExecutionState)
        return adapter.validate_json(path.read_text(encoding="utf-8"))
