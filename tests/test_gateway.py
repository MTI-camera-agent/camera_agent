from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from schemas.shooting import (
    AestheticInstructionDraft,
    GuidanceOverlayPayload,
    IntentConflict,
    IntentPhaseResult,
    IntentQuestion,
    PlanAndEditInstruction,
    ReferencePreviewPayload,
    SceneFacts,
    ShootingPlanPayload,
    ShootingPlanStep,
)
from services.gateway.image_util import save_resized_frame
from services.gateway.main import create_app
from services.gateway.reference_preview import PreviewRecord
from workflow.shooting_loop import ShootingLoopResult


def _jpeg_bytes(size: tuple[int, int] = (640, 480), color=(20, 80, 120)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture()
def mock_phase() -> IntentPhaseResult:
    return IntentPhaseResult(
        draft_goal="断桥游客照",
        questions=[
            IntentQuestion(
                question_id="q1",
                text="人物位置？",
                options=["右侧", "居中"],
            )
        ],
        conflicts=[
            IntentConflict(summary="右侧 vs 偏左", user_side="右侧", scene_side="偏左")
        ],
        scene_facts=SceneFacts(narrative="人物偏左"),
        aesthetic_draft=AestheticInstructionDraft(instruction="人物居中"),
    )


@pytest.fixture()
def mock_plan(mock_phase: IntentPhaseResult) -> PlanAndEditInstruction:
    return PlanAndEditInstruction(
        shooting_plan=ShootingPlanPayload(
            goal="断桥游客照，人物右侧",
            steps=[
                ShootingPlanStep(step_id="s0_intent", title="意图确认", status="completed"),
                ShootingPlanStep(step_id="s1_coarse_act", title="粗调", status="in_progress"),
            ],
        ),
        coarse_guidance=GuidanceOverlayPayload(advice_text="站到右侧三分线"),
        edit_instruction="人物置于右侧三分线。",
        scene_facts=mock_phase.scene_facts,
        aesthetic_draft=mock_phase.aesthetic_draft,
        intent_resolution_notes="用户坚持右侧",
    )


@pytest.fixture()
def gateway_client(tmp_path: Path, mock_phase: IntentPhaseResult, mock_plan: PlanAndEditInstruction):
    loop = MagicMock()
    loop.collect_intent_phase.return_value = mock_phase

    def _confirm(**kwargs):
        plan_dir = kwargs.get("plan_dir") or tmp_path / "plans"
        plan_dir = Path(plan_dir)
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plan_dir / "shooting_plan.json"
        plan_path.write_text("{}", encoding="utf-8")
        return ShootingLoopResult(
            intent_phase=kwargs["intent_phase"],
            plan_bundle=mock_plan,
            plan_path=plan_path,
        )

    loop.confirm_and_plan.side_effect = _confirm

    config = {
        "gateway": {
            "demo_token": "secret-demo",
            "max_frame_long_edge": 1280,
            "frames_dir": str(tmp_path / "frames"),
            "plans_dir": str(tmp_path / "plans"),
            "web_dir": str(Path(__file__).resolve().parents[1] / "frontend" / "web"),
            "cors_origins": ["*"],
        },
        "logging": {"level": "WARNING", "console_level": "WARNING"},
    }
    app = create_app(config=config, attach_loop=False)
    app.state.shooting_loop = loop
    preview = MagicMock()
    preview.get_payload.return_value = ReferencePreviewPayload(
        status="generating", source_frame_id=""
    )
    app.state.reference_preview_service = preview
    with TestClient(app) as client:
        yield client, loop


def test_create_and_get_session_requires_token(gateway_client) -> None:
    client, _ = gateway_client
    assert client.post("/api/v1/sessions").status_code == 401
    res = client.post("/api/v1/sessions", headers={"X-Demo-Token": "secret-demo"})
    assert res.status_code == 200
    session_id = res.json()["sessionId"]
    got = client.get(
        f"/api/v1/sessions/{session_id}",
        headers={"X-Demo-Token": "secret-demo"},
    )
    assert got.status_code == 200
    assert got.json()["status"] == "created"


def test_submit_and_confirm_intent(gateway_client, mock_phase: IntentPhaseResult) -> None:
    client, loop = gateway_client
    headers = {"X-Demo-Token": "secret-demo"}
    session_id = client.post("/api/v1/sessions", headers=headers).json()["sessionId"]

    files = {"frame": ("frame.jpg", _jpeg_bytes(), "image/jpeg")}
    data = {"userIntent": "在断桥拍游客照，人物在右侧"}
    submit = client.post(
        f"/api/v1/sessions/{session_id}/submit-intent",
        headers=headers,
        files=files,
        data=data,
    )
    assert submit.status_code == 200, submit.text
    body = submit.json()
    assert body["draftGoal"] == mock_phase.draft_goal
    assert body["questions"][0]["questionId"] == "q1"
    loop.collect_intent_phase.assert_called_once()

    confirm = client.post(
        f"/api/v1/sessions/{session_id}/confirm-intent",
        headers=headers,
        json={"answers": [{"questionId": "q1", "value": "右侧"}]},
    )
    assert confirm.status_code == 200, confirm.text
    plan = confirm.json()
    assert plan["editInstruction"].startswith("人物置于右侧")
    assert plan["coarseGuidance"]["adviceText"] == "站到右侧三分线"
    assert plan["referencePreview"]["status"] == "generating"
    assert plan["shootingPlan"]["goal"]

    status = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert status["status"] == "planned"


def test_bad_frame_returns_400(gateway_client) -> None:
    client, _ = gateway_client
    headers = {"X-Demo-Token": "secret-demo"}
    session_id = client.post("/api/v1/sessions", headers=headers).json()["sessionId"]
    files = {"frame": ("frame.txt", b"not-an-image", "text/plain")}
    data = {"userIntent": "test"}
    res = client.post(
        f"/api/v1/sessions/{session_id}/submit-intent",
        headers=headers,
        files=files,
        data=data,
    )
    assert res.status_code == 400


def test_confirm_without_submit_conflict(gateway_client) -> None:
    client, _ = gateway_client
    headers = {"X-Demo-Token": "secret-demo"}
    session_id = client.post("/api/v1/sessions", headers=headers).json()["sessionId"]
    res = client.post(
        f"/api/v1/sessions/{session_id}/confirm-intent",
        headers=headers,
        json={"answers": [{"questionId": "q1", "value": "右侧"}]},
    )
    assert res.status_code == 409


def test_static_index(gateway_client) -> None:
    client, _ = gateway_client
    res = client.get("/")
    assert res.status_code == 200
    assert "CameraAgent" in res.text
    css = client.get("/static/styles.css")
    assert css.status_code == 200


def test_save_resized_frame_clamps_long_edge(tmp_path: Path) -> None:
    raw = _jpeg_bytes((2000, 1000))
    dest = tmp_path / "out.jpg"
    save_resized_frame(raw, dest, max_long_edge=1280)
    with Image.open(dest) as img:
        assert max(img.size) == 1280


def test_reference_preview_generating_after_confirm(gateway_client) -> None:
    client, _ = gateway_client
    headers = {"X-Demo-Token": "secret-demo"}
    session_id = client.post("/api/v1/sessions", headers=headers).json()["sessionId"]
    files = {"frame": ("frame.jpg", _jpeg_bytes(), "image/jpeg")}
    data = {"userIntent": "在断桥拍游客照，人物在右侧"}
    client.post(
        f"/api/v1/sessions/{session_id}/submit-intent",
        headers=headers,
        files=files,
        data=data,
    )
    confirm = client.post(
        f"/api/v1/sessions/{session_id}/confirm-intent",
        headers=headers,
        json={"answers": [{"questionId": "q1", "value": "右侧"}]},
    )
    assert confirm.status_code == 200
    assert confirm.json()["referencePreview"]["status"] == "generating"
    preview = client.app.state.reference_preview_service
    preview.kickoff.assert_called_once()
    assert preview.kickoff.call_args.kwargs["session_id"] == session_id


def test_get_reference_preview_ready(gateway_client) -> None:
    client, _ = gateway_client
    headers = {"X-Demo-Token": "secret-demo"}
    session_id = client.post("/api/v1/sessions", headers=headers).json()["sessionId"]
    preview = client.app.state.reference_preview_service
    preview.get_payload.return_value = ReferencePreviewPayload(
        status="ready",
        data_ref=f"/api/v1/sessions/{session_id}/reference-preview.png",
        source_frame_id=session_id,
        latency_ms=1234,
        generator="qwen2511",
    )
    res = client.get(
        f"/api/v1/sessions/{session_id}/reference-preview", headers=headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ready"
    assert body["dataRef"].endswith("reference-preview.png")
    assert body["latencyMs"] == 1234
    assert body["generator"] == "qwen2511"


def test_get_reference_preview_not_found(gateway_client) -> None:
    client, _ = gateway_client
    headers = {"X-Demo-Token": "secret-demo"}
    session_id = client.post("/api/v1/sessions", headers=headers).json()["sessionId"]
    preview = client.app.state.reference_preview_service
    preview.get_payload.return_value = None
    res = client.get(
        f"/api/v1/sessions/{session_id}/reference-preview", headers=headers
    )
    assert res.status_code == 404


def _write_png(path: Path, size=(64, 64)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (9, 8, 7)).save(path, format="PNG")
    return path


def test_reference_preview_png_ready(gateway_client, tmp_path: Path) -> None:
    client, _ = gateway_client
    headers = {"X-Demo-Token": "secret-demo"}
    session_id = client.post("/api/v1/sessions", headers=headers).json()["sessionId"]
    png = _write_png(tmp_path / "rp.png")
    preview = client.app.state.reference_preview_service
    preview.get.return_value = PreviewRecord(
        preview_id="rp-1",
        session_id=session_id,
        source_frame_id=session_id,
        generator="qwen2511",
        status="ready",
        output_path=png,
    )
    res = client.get(
        f"/api/v1/sessions/{session_id}/reference-preview.png", headers=headers
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/png")


def test_reference_preview_png_not_ready(gateway_client) -> None:
    client, _ = gateway_client
    headers = {"X-Demo-Token": "secret-demo"}
    session_id = client.post("/api/v1/sessions", headers=headers).json()["sessionId"]
    preview = client.app.state.reference_preview_service
    preview.get.return_value = PreviewRecord(
        preview_id="rp-1",
        session_id=session_id,
        source_frame_id=session_id,
        generator="qwen2511",
        status="generating",
        output_path=None,
    )
    res = client.get(
        f"/api/v1/sessions/{session_id}/reference-preview.png", headers=headers
    )
    assert res.status_code == 404
