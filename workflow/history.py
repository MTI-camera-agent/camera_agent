from __future__ import annotations

from schemas.state import ExecutionState


def summarize_state(state: ExecutionState) -> str:
    artifacts = [
        f"{alias}: kind={artifact.kind}, path={artifact.path}, data={artifact.data}"
        for alias, artifact in state.artifacts.items()
    ]
    history = [
        f"{entry.status} action={entry.action.action} output={entry.action.output} message={entry.message}"
        for entry in state.history[-12:]
    ]
    evaluations = [
        f"satisfied={report.satisfied} score={report.score:.2f} summary={report.summary}"
        for report in state.evaluations[-4:]
    ]
    return "\n".join(
        [
            f"iteration={state.iteration}",
            f"original_image={state.original_image}",
            f"current_image={state.current_image}",
            f"artifacts={artifacts or 'none'}",
            f"recent_history={history or 'none'}",
            f"evaluations={evaluations or 'none'}",
        ]
    )
