from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


_NOISY_LOGGERS = ("httpx", "httpcore", "openai", "httpx._client")


def configure_logging(
    level: str = "INFO",
    *,
    console_level: str | None = None,
    file: str | Path | None = None,
    httpx_level: str = "WARNING",
    config: dict[str, Any] | None = None,
) -> None:
    """Configure dual-channel logging: quiet console, detailed optional file.

    Prefer ``config`` from ``config.yaml`` ``logging:`` block when provided.
    """
    if config:
        level = str(config.get("level") or level)
        console_level = (
            str(config["console_level"])
            if config.get("console_level") is not None
            else console_level
        )
        if config.get("file") is not None:
            file = config.get("file")
        if config.get("httpx_level") is not None:
            httpx_level = str(config["httpx_level"])

    file_level = getattr(logging, str(level).upper(), logging.INFO)
    stream_level = getattr(
        logging,
        str(console_level or "WARNING").upper(),
        logging.WARNING,
    )
    lib_level = getattr(logging, str(httpx_level).upper(), logging.WARNING)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(min(file_level, stream_level))

    console = logging.StreamHandler()
    console.setLevel(stream_level)
    console.setFormatter(fmt)
    root.addHandler(console)

    if file:
        path = Path(str(file))
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setLevel(file_level)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(lib_level)
