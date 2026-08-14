"""Async reference_preview generation for the shooting gateway.

Process-local, single-worker friendly: one daemon thread per kickoff + a
Lock-guarded store keyed by ``session_id`` (one active preview per session,
matching the ``GET /sessions/{id}/reference-preview`` route). Multi-worker or
Redis durability is a later concern (open issue O6).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from schemas.shooting import ReferencePreviewPayload, ReferencePreviewStatus
from skills.reference_image import ReferenceImageSkill
from utils.file import ensure_dir


@dataclass
class PreviewRecord:
    preview_id: str
    session_id: str
    source_frame_id: str
    generator: str
    status: ReferencePreviewStatus = "generating"
    data_ref: str | None = None
    width: int | None = None
    height: int | None = None
    latency_ms: int | None = None
    error_message: str | None = None
    output_path: Path | None = None


class ReferencePreviewService:
    """Kicks off Qwen2511 (or FLUX fallback) preview generation in a background thread."""

    def __init__(
        self,
        *,
        previews_dir: Path,
        primary: ReferenceImageSkill,
        fallback: ReferenceImageSkill | None = None,
        poll_interval_seconds: float = 1.5,
    ) -> None:
        self._previews_dir = ensure_dir(previews_dir)
        self._primary = primary
        self._fallback = fallback
        self._poll_interval = float(poll_interval_seconds)
        self._records: dict[str, PreviewRecord] = {}
        self._lock = threading.Lock()

    @property
    def poll_interval_seconds(self) -> float:
        return self._poll_interval

    @property
    def previews_dir(self) -> Path:
        return self._previews_dir

    def get(self, session_id: str) -> PreviewRecord | None:
        with self._lock:
            return self._records.get(session_id)

    def get_payload(self, session_id: str) -> ReferencePreviewPayload | None:
        with self._lock:
            record = self._records.get(session_id)
            return _record_to_payload(record) if record is not None else None

    def kickoff(
        self,
        *,
        session_id: str,
        frame_path: Path,
        edit_instruction: str,
        source_frame_id: str,
        preview_id: str | None = None,
    ) -> PreviewRecord:
        if preview_id is None:
            preview_id = f"rp-{uuid4().hex[:10]}"
        record = PreviewRecord(
            preview_id=preview_id,
            session_id=session_id,
            source_frame_id=source_frame_id,
            generator=self._primary.generator,
            status="generating",
        )
        with self._lock:
            self._records[session_id] = record
        thread = threading.Thread(
            target=self._run,
            args=(record, frame_path, edit_instruction),
            daemon=True,
            name=f"reference-preview-{session_id}",
        )
        thread.start()
        return record

    def _run(
        self,
        record: PreviewRecord,
        frame_path: Path,
        edit_instruction: str,
    ) -> None:
        out_dir = ensure_dir(self._previews_dir / record.session_id)
        output_path = out_dir / f"{record.preview_id}.png"
        try:
            result = self._primary.generate(
                frame_path=frame_path,
                edit_instruction=edit_instruction,
                output_path=output_path,
            )
        except Exception as exc:  # noqa: BLE001 — map to failed/fallback
            if self._fallback is None:
                self._mark(record, status="failed", error_message=str(exc))
                return
            try:
                result = self._fallback.generate(
                    frame_path=frame_path,
                    edit_instruction=edit_instruction,
                    output_path=output_path,
                )
            except Exception as fb_exc:  # noqa: BLE001
                self._mark(record, status="failed", error_message=str(fb_exc))
                return
        self._mark(
            record,
            status="ready",
            data_ref=f"/api/v1/sessions/{record.session_id}/reference-preview.png",
            output_path=result.output_path,
            width=result.width,
            height=result.height,
            latency_ms=result.latency_ms,
            generator=result.generator,
        )

    def _mark(self, record: PreviewRecord, **fields: object) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(record, key, value)


def _record_to_payload(record: PreviewRecord) -> ReferencePreviewPayload:
    return ReferencePreviewPayload(
        preview_id=record.preview_id,
        status=record.status,
        data_ref=record.data_ref,
        source_frame_id=record.source_frame_id,
        width=record.width,
        height=record.height,
        latency_ms=record.latency_ms,
        generator=record.generator,
        error_message=record.error_message,
    )
