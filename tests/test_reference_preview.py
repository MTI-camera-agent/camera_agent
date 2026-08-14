"""PR1 reference-preview unit tests (no GPU/network: fake image client)."""

from __future__ import annotations

import json
from pathlib import Path
from time import sleep

from PIL import Image

from services.gateway.reference_preview import ReferencePreviewService
from skills.reference_image import (
    PRESERVE_IDENTITY_SUFFIX,
    ReferenceImageSkill,
)


class FakeImageClient:
    """Duck-typed ImageGenerationClient: writes a PNG + sidecar on edit()."""

    def __init__(self, *, generator: str = "qwen2511", fail: bool = False) -> None:
        self.generator = generator
        self._fail = fail
        self.last_prompt: str | None = None
        self.calls = 0

    def generate(self, **kwargs):  # pragma: no cover - not used by the skill
        raise RuntimeError("FakeImageClient is edit-only")

    def edit(self, *, image_path, prompt, output_path, size="auto"):
        del size
        self.calls += 1
        self.last_prompt = prompt
        if self._fail:
            raise RuntimeError(f"{self.generator} edit failed (fake)")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (512, 512), (12, 34, 56)).save(output_path, format="PNG")
        output_path.with_suffix(".json").write_text(
            json.dumps({"provider": self.generator, "latency_seconds": 0.05}),
            encoding="utf-8",
        )
        return output_path

    def healthcheck(self) -> bool:
        return not self._fail


def _make_frame(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), (200, 200, 200)).save(path, format="JPEG")
    return path


def _wait_for_status(
    service: ReferencePreviewService, session_id: str, status: str, timeout: float = 2.0
) -> None:
    elapsed = 0.0
    while elapsed < timeout:
        payload = service.get_payload(session_id)
        if payload is not None and payload.status == status:
            return
        sleep(0.01)
        elapsed += 0.01
    raise AssertionError(
        f"preview for {session_id} did not reach status={status} within {timeout}s"
    )


def test_compose_prompt_appends_preserve_suffix() -> None:
    skill = ReferenceImageSkill(client=FakeImageClient(), generator="qwen2511")
    prompt = skill.compose_prompt("人物置于右侧三分线")
    assert "人物置于右侧三分线" in prompt
    assert PRESERVE_IDENTITY_SUFFIX in prompt
    assert "保持人物身份" in prompt
    assert "不得引入" in prompt


def test_compose_prompt_rejects_empty_instruction() -> None:
    skill = ReferenceImageSkill(client=FakeImageClient(), generator="qwen2511")
    for empty in ("", "   "):
        try:
            skill.compose_prompt(empty)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {empty!r}")


def test_skill_generate_writes_png_and_metadata(tmp_path: Path) -> None:
    client = FakeImageClient()
    skill = ReferenceImageSkill(client=client, generator="qwen2511")
    frame = _make_frame(tmp_path / "frame.jpg")
    out = tmp_path / "previews" / "rp-1.png"

    result = skill.generate(
        frame_path=frame,
        edit_instruction="人物置于右侧三分线",
        output_path=out,
    )
    assert result.output_path == out
    assert out.is_file()
    assert result.latency_ms >= 0
    assert (result.width, result.height) == (512, 512)
    assert result.generator == "qwen2511"
    # prompt sent to the client carried both instruction and preserve suffix
    assert client.last_prompt is not None
    assert "人物置于右侧三分线" in client.last_prompt
    assert PRESERVE_IDENTITY_SUFFIX in client.last_prompt


def test_skill_generate_requires_existing_frame(tmp_path: Path) -> None:
    skill = ReferenceImageSkill(client=FakeImageClient(), generator="qwen2511")
    try:
        skill.generate(
            frame_path=tmp_path / "missing.jpg",
            edit_instruction="x",
            output_path=tmp_path / "out.png",
        )
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError for missing frame")


def test_service_kickoff_transitions_to_ready(tmp_path: Path) -> None:
    service = ReferencePreviewService(
        previews_dir=tmp_path / "previews",
        primary=ReferenceImageSkill(client=FakeImageClient(), generator="qwen2511"),
    )
    frame = _make_frame(tmp_path / "frame.jpg")
    record = service.kickoff(
        session_id="sess-1",
        frame_path=frame,
        edit_instruction="人物置于右侧三分线",
        source_frame_id="sess-1",
    )
    assert record.status == "generating"
    _wait_for_status(service, "sess-1", "ready")
    payload = service.get_payload("sess-1")
    assert payload is not None
    assert payload.status == "ready"
    assert payload.generator == "qwen2511"
    assert payload.data_ref == "/api/v1/sessions/sess-1/reference-preview.png"
    assert payload.latency_ms is not None and payload.latency_ms >= 0
    assert (tmp_path / "previews" / "sess-1" / f"{record.preview_id}.png").is_file()


def test_service_marks_failed_without_fallback(tmp_path: Path) -> None:
    service = ReferencePreviewService(
        previews_dir=tmp_path / "previews",
        primary=ReferenceImageSkill(
            client=FakeImageClient(fail=True), generator="qwen2511"
        ),
    )
    frame = _make_frame(tmp_path / "frame.jpg")
    service.kickoff(
        session_id="sess-2",
        frame_path=frame,
        edit_instruction="人物置于右侧三分线",
        source_frame_id="sess-2",
    )
    _wait_for_status(service, "sess-2", "failed")
    payload = service.get_payload("sess-2")
    assert payload is not None
    assert payload.status == "failed"
    assert payload.error_message
    assert payload.data_ref is None


def test_service_falls_back_to_flux(tmp_path: Path) -> None:
    primary_client = FakeImageClient(generator="qwen2511", fail=True)
    fallback_client = FakeImageClient(generator="flux")
    primary = ReferenceImageSkill(client=primary_client, generator="qwen2511")
    fallback = ReferenceImageSkill(client=fallback_client, generator="flux")
    service = ReferencePreviewService(
        previews_dir=tmp_path / "previews",
        primary=primary,
        fallback=fallback,
    )
    frame = _make_frame(tmp_path / "frame.jpg")
    service.kickoff(
        session_id="sess-3",
        frame_path=frame,
        edit_instruction="人物置于右侧三分线",
        source_frame_id="sess-3",
    )
    _wait_for_status(service, "sess-3", "ready")
    payload = service.get_payload("sess-3")
    assert payload is not None
    assert payload.status == "ready"
    assert payload.generator == "flux"  # fallback generator recorded
    assert primary_client.calls == 1
    assert fallback_client.calls == 1


def test_service_get_payload_unknown_session(tmp_path: Path) -> None:
    service = ReferencePreviewService(
        previews_dir=tmp_path / "previews",
        primary=ReferenceImageSkill(client=FakeImageClient(), generator="qwen2511"),
    )
    assert service.get_payload("unknown") is None
    assert service.get("unknown") is None
