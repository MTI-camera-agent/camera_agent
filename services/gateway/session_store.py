from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

from schemas.shooting import IntentPhaseResult, PlanAndEditInstruction, ReferencePreviewPayload

SessionStatus = Literal["created", "intent_ready", "planned", "error"]


def _new_session_id() -> str:
    return f"sess-{uuid4().hex[:12]}"


@dataclass
class SessionRecord:
    session_id: str
    created_at: float
    status: SessionStatus = "created"
    user_intent: str | None = None
    frame_path: Path | None = None
    intent_phase: IntentPhaseResult | None = None
    plan_bundle: PlanAndEditInstruction | None = None
    plan_path: Path | None = None
    reference_preview: ReferencePreviewPayload | None = None
    error_message: str | None = None


@dataclass
class InMemorySessionStore:
    """O6: first version is process-local memory only."""

    _sessions: dict[str, SessionRecord] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def create(self) -> SessionRecord:
        record = SessionRecord(session_id=_new_session_id(), created_at=time.time())
        with self._lock:
            self._sessions[record.session_id] = record
        return record

    def get(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            return self._sessions.get(session_id)

    def upsert(self, record: SessionRecord) -> SessionRecord:
        with self._lock:
            self._sessions[record.session_id] = record
        return record
