from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from schemas.shooting import (
    IntentAnswer,
    IntentPhaseResult,
    PlanAndEditInstruction,
    ReferencePreviewPayload,
)
from services.gateway.deps import (
    GatewaySettings,
    get_loop,
    get_reference_preview_service,
    get_settings,
    get_store,
    require_demo_token,
)
from services.gateway.image_util import (
    FrameValidationError,
    save_resized_frame,
    validate_frame_content_type,
)
from services.gateway.reference_preview import ReferencePreviewService
from services.gateway.session_store import InMemorySessionStore, SessionRecord
from utils.file import ensure_dir
from workflow.shooting_loop import ShootingLoop

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_demo_token)])


class CreateSessionResponse(BaseModel):
    session_id: str = Field(..., alias="sessionId")

    model_config = {"populate_by_name": True}


class ConfirmIntentRequest(BaseModel):
    answers: list[IntentAnswer] = Field(..., min_length=1)

    model_config = {"populate_by_name": True}


class SessionStatusResponse(BaseModel):
    session_id: str = Field(..., alias="sessionId")
    status: str
    user_intent: str | None = Field(default=None, alias="userIntent")
    error_message: str | None = Field(default=None, alias="errorMessage")
    intent_phase: IntentPhaseResult | None = Field(default=None, alias="intentPhase")
    plan_bundle: PlanAndEditInstruction | None = Field(default=None, alias="planBundle")
    plan_path: str | None = Field(default=None, alias="planPath")
    reference_preview: ReferencePreviewPayload | None = Field(
        default=None, alias="referencePreview"
    )

    model_config = {"populate_by_name": True}


def _require_session(store: InMemorySessionStore, session_id: str) -> SessionRecord:
    record = store.get(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
    return record


@router.post("/sessions", response_model=CreateSessionResponse)
def create_session(store: InMemorySessionStore = Depends(get_store)) -> CreateSessionResponse:
    record = store.create()
    return CreateSessionResponse(session_id=record.session_id)


@router.get("/sessions/{session_id}", response_model=SessionStatusResponse)
def get_session(
    session_id: str,
    store: InMemorySessionStore = Depends(get_store),
) -> SessionStatusResponse:
    record = _require_session(store, session_id)
    return SessionStatusResponse(
        session_id=record.session_id,
        status=record.status,
        user_intent=record.user_intent,
        error_message=record.error_message,
        intent_phase=record.intent_phase,
        plan_bundle=record.plan_bundle,
        plan_path=str(record.plan_path) if record.plan_path else None,
        reference_preview=record.reference_preview,
    )


@router.post(
    "/sessions/{session_id}/submit-intent",
    response_model=IntentPhaseResult,
)
async def submit_intent(
    session_id: str,
    user_intent: str = Form(..., alias="userIntent"),
    frame: UploadFile = File(...),
    store: InMemorySessionStore = Depends(get_store),
    loop: ShootingLoop = Depends(get_loop),
    settings: GatewaySettings = Depends(get_settings),
) -> IntentPhaseResult:
    record = _require_session(store, session_id)
    intent = (user_intent or "").strip()
    if not intent:
        raise HTTPException(status_code=422, detail="userIntent must be non-empty")

    try:
        validate_frame_content_type(frame.content_type, frame.filename)
        raw = await frame.read()
        frames_dir = ensure_dir(settings.frames_dir)
        dest = frames_dir / f"{session_id}.jpg"
        save_resized_frame(raw, dest, max_long_edge=settings.max_frame_long_edge)
    except FrameValidationError as exc:
        record.status = "error"
        record.error_message = str(exc)
        store.upsert(record)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        phase = loop.collect_intent_phase(image_path=dest, user_intent=intent)
    except Exception as exc:  # noqa: BLE001 — map runtime failures to 502
        record.status = "error"
        record.error_message = str(exc)
        record.frame_path = dest
        record.user_intent = intent
        store.upsert(record)
        raise HTTPException(
            status_code=502,
            detail=f"Intent analysis failed: {exc}",
        ) from exc

    record.user_intent = intent
    record.frame_path = dest
    record.intent_phase = phase
    record.plan_bundle = None
    record.plan_path = None
    record.error_message = None
    record.status = "intent_ready"
    store.upsert(record)
    return phase


@router.post(
    "/sessions/{session_id}/confirm-intent",
    response_model=PlanAndEditInstruction,
)
def confirm_intent(
    session_id: str,
    body: ConfirmIntentRequest,
    store: InMemorySessionStore = Depends(get_store),
    loop: ShootingLoop = Depends(get_loop),
    settings: GatewaySettings = Depends(get_settings),
    preview_service: ReferencePreviewService = Depends(get_reference_preview_service),
) -> PlanAndEditInstruction:
    record = _require_session(store, session_id)
    if record.intent_phase is None or not record.user_intent:
        raise HTTPException(
            status_code=409,
            detail="Session has no intent phase; call submit-intent first",
        )

    session_plan_dir = ensure_dir(Path(settings.plans_dir) / session_id)
    try:
        result = loop.confirm_and_plan(
            user_intent=record.user_intent,
            intent_phase=record.intent_phase,
            answers=body.answers,
            plan_dir=session_plan_dir,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        record.status = "error"
        record.error_message = str(exc)
        store.upsert(record)
        raise HTTPException(
            status_code=502,
            detail=f"Plan generation failed: {exc}",
        ) from exc

    bundle = result.plan_bundle
    preview_payload = _kickoff_reference_preview(
        preview_service=preview_service,
        session_id=session_id,
        frame_path=record.frame_path,
        edit_instruction=bundle.edit_instruction,
    )
    if preview_payload is not None:
        bundle = bundle.model_copy(update={"reference_preview": preview_payload})

    record.plan_bundle = bundle
    record.plan_path = result.plan_path
    record.reference_preview = preview_payload
    record.status = "planned"
    record.error_message = None
    store.upsert(record)
    return bundle


def _kickoff_reference_preview(
    *,
    preview_service: ReferencePreviewService,
    session_id: str,
    frame_path: Path | None,
    edit_instruction: str,
) -> ReferencePreviewPayload | None:
    """Kick off async Qwen2511 preview; return the generating payload (or None)."""
    if frame_path is None or not Path(frame_path).is_file():
        return None
    preview_service.kickoff(
        session_id=session_id,
        frame_path=Path(frame_path),
        edit_instruction=edit_instruction,
        source_frame_id=session_id,
    )
    return preview_service.get_payload(session_id)


@router.get(
    "/sessions/{session_id}/reference-preview",
    response_model=ReferencePreviewPayload,
)
def get_reference_preview(
    session_id: str,
    store: InMemorySessionStore = Depends(get_store),
    preview_service: ReferencePreviewService = Depends(get_reference_preview_service),
) -> ReferencePreviewPayload:
    _require_session(store, session_id)
    payload = preview_service.get_payload(session_id)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail="No reference preview for this session; confirm-intent first",
        )
    return payload


@router.get("/sessions/{session_id}/reference-preview.png")
def get_reference_preview_image(
    session_id: str,
    store: InMemorySessionStore = Depends(get_store),
    preview_service: ReferencePreviewService = Depends(get_reference_preview_service),
) -> FileResponse:
    _require_session(store, session_id)
    record = preview_service.get(session_id)
    if record is None or record.status != "ready" or record.output_path is None:
        raise HTTPException(
            status_code=404,
            detail="Reference preview is not ready; poll /reference-preview",
        )
    output_path = Path(record.output_path)
    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="Reference preview file missing")
    return FileResponse(output_path, media_type="image/png")
