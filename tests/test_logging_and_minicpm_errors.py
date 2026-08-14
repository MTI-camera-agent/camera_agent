from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from models.agno_structured_vision import AgnoStructuredVisionClient
from models.factory import build_structured_vision_client
from schemas.state import EvaluationReport
from utils.logger import configure_logging

REPO = Path(__file__).resolve().parents[1]


def test_configure_logging_writes_file_and_keeps_console_quiet(tmp_path: Path) -> None:
    log_file = tmp_path / "camera_agent.log"
    configure_logging(
        config={
            "level": "INFO",
            "console_level": "WARNING",
            "file": str(log_file),
            "httpx_level": "WARNING",
        }
    )
    logging.getLogger("camera_agent.test").info("file-only-info")
    logging.getLogger("httpx").info("httpx-should-be-filtered")
    assert log_file.is_file()
    text = log_file.read_text(encoding="utf-8")
    assert "file-only-info" in text
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING


def test_reflection_prompt_requires_bare_json() -> None:
    text = (REPO / "prompts" / "reflection.md").read_text(encoding="utf-8")
    assert "only" in text.lower()
    assert "satisfied" in text
    assert "score" in text
    assert "missing" in text
    assert "suggestions" in text
    assert "summary" in text
    assert "JSON" in text or "json" in text


def test_minicpm_route_denied_raises_runtime_error() -> None:
    client = AgnoStructuredVisionClient.__new__(AgnoStructuredVisionClient)
    client._provider = "agno.openai_compatible"
    with pytest.raises(RuntimeError, match="probe_minicpm_api"):
        client._raise_for_provider_string_error(
            "无法根据 model 定位推理服务",
            EvaluationReport,
        )


def test_timeout_string_raises_deepseek_runtime_error() -> None:
    client = AgnoStructuredVisionClient.__new__(AgnoStructuredVisionClient)
    client._provider = "agno.deepseek"
    with pytest.raises(RuntimeError, match="DeepSeek"):
        client._raise_for_provider_string_error(
            "Request timed out.",
            EvaluationReport,
        )


def test_try_parse_schema_from_embedded_json() -> None:
    prose = (
        "Looking at the images, here is my judgment:\n"
        '{"satisfied": true, "score": 0.9, "missing": [], '
        '"suggestions": [], "summary": "Front view achieved."}\n'
    )
    report = AgnoStructuredVisionClient._try_parse_schema_from_text(
        prose, EvaluationReport
    )
    assert report is not None
    assert report.satisfied is True
    assert report.score == 0.9


def test_try_parse_schema_rejects_prose_without_braces() -> None:
    prose = (
        "Looking at the current result, the person's pose appears front-facing.\n"
        "satisfied: true\nscore: 0.8\n"
    )
    assert (
        AgnoStructuredVisionClient._try_parse_schema_from_text(prose, EvaluationReport)
        is None
    )


def test_generate_recovers_json_embedded_in_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AgnoStructuredVisionClient.__new__(AgnoStructuredVisionClient)
    client._provider = "agno.openai_compatible"
    client._use_json_mode = True
    client._retries = 1
    client._model = object()
    client._vision_bridge = None

    monkeypatch.setattr(
        client,
        "_prepare_prompt_and_images",
        lambda **_: ("prompt", []),
    )

    fake_response = MagicMock()
    fake_response.content = (
        'Here you go: {"satisfied": false, "score": 0.3, '
        '"missing": ["still angled"], "suggestions": ["retry pose"], '
        '"summary": "Not front-facing yet."}'
    )

    class FakeAgent:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            pass

        def run(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
            return fake_response

    monkeypatch.setattr("models.agno_structured_vision.Agent", FakeAgent)

    report = client.generate(
        prompt="x",
        output_schema=EvaluationReport,
        image_paths=[],
    )
    assert report.satisfied is False
    assert "angled" in report.missing[0]


def test_generate_maps_route_denied_string_to_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AgnoStructuredVisionClient.__new__(AgnoStructuredVisionClient)
    client._provider = "agno.openai_compatible"
    client._use_json_mode = True
    client._retries = 1
    client._model = object()
    client._vision_bridge = None

    monkeypatch.setattr(
        client,
        "_prepare_prompt_and_images",
        lambda **_: ("prompt", []),
    )

    fake_response = MagicMock()
    fake_response.content = "lis_route_denied: 无法根据 model 定位推理服务"

    class FakeAgent:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            pass

        def run(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
            return fake_response

    monkeypatch.setattr(
        "models.agno_structured_vision.Agent",
        FakeAgent,
    )

    with pytest.raises(RuntimeError, match="status_minicpm_server|MINICPM_API_KEY"):
        client.generate(
            prompt="x",
            output_schema=EvaluationReport,
            image_paths=[],
        )


def test_generate_prose_without_json_raises_clear_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AgnoStructuredVisionClient.__new__(AgnoStructuredVisionClient)
    client._provider = "agno.openai_compatible"
    client._use_json_mode = True
    client._retries = 1
    client._model = object()
    client._vision_bridge = None

    monkeypatch.setattr(
        client,
        "_prepare_prompt_and_images",
        lambda **_: ("prompt", []),
    )
    fake_response = MagicMock()
    fake_response.content = (
        "Looking at the current result, satisfied: true score roughly high"
    )

    class FakeAgent:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            pass

        def run(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
            return fake_response

    monkeypatch.setattr("models.agno_structured_vision.Agent", FakeAgent)

    with pytest.raises(RuntimeError, match="response_format|non-JSON"):
        client.generate(
            prompt="x",
            output_schema=EvaluationReport,
            image_paths=[],
        )


def test_openai_compatible_passes_timeout_seconds() -> None:
    with patch("agno.models.openai.like.OpenAILike") as mock_cls:
        mock_cls.return_value = MagicMock()
        build_structured_vision_client(
            {
                "provider": "agno.openai_compatible",
                "model_id": "MiniCPM-V-4.6",
                "base_url": "http://127.0.0.1:8001/v1",
                "timeout_seconds": 120,
                "use_json_mode": True,
            }
        )
    assert mock_cls.call_args.kwargs["timeout"] == 120.0
