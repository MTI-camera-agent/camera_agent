"""Immutable image fixtures for deterministic v2 replay.

The replay harness requires exact immutable observation/image fixtures whose
source-byte hash is stable across runs (``docs/CAMERA_AGENT_V2_EVALUATION.md``
§3). These fixtures hand out ``ContextImage`` values whose ``bytes_hash`` is a
fixed sha256 of the fixture bytes, so a test can assert byte provenance and
correlation without depending on live capture.

Fixtures are immutable: their bytes are frozen ``bytes`` and their hash is
computed once at construction. They are not editable, not generated on demand,
and never enter live Evidence or Readiness.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from camera_agent.v2.identity import new_identity
from camera_agent.v2.seams import ContextImage

if TYPE_CHECKING:
    from .identity import DeterministicIdentityFactory


@dataclass(frozen=True, slots=True)
class ImageFixture:
    """One immutable image fixture with a stable source-byte hash.

    ``bytes`` are frozen at construction; ``bytes_hash`` is ``sha256:<hex>``. A
    test supplies a stable ``image_id`` (or a deterministic factory mints one)
    to produce an immutable ``ContextImage`` carrying the same provenance.
    """

    bytes_: bytes
    bytes_hash: str
    width: int
    height: int
    mime_type: str

    def __post_init__(self) -> None:
        if not self.bytes_:
            raise ValueError("image fixture bytes must be nonempty")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("image fixture dimensions must be positive")
        if self.mime_type not in {"image/jpeg", "image/png"}:
            raise ValueError("image fixture must be JPEG or PNG")
        expected = "sha256:" + hashlib.sha256(self.bytes_).hexdigest()
        if self.bytes_hash != expected:
            raise ValueError("image fixture bytes_hash must be sha256 of bytes_")

    def to_context_image(self, image_id: UUID) -> ContextImage:
        """Build an immutable ``ContextImage`` bound to ``image_id``."""
        return ContextImage(
            image_id=image_id,
            bytes_hash=self.bytes_hash,
            width=self.width,
            height=self.height,
        )

    def to_context_image_with_factory(
        self, factory: "DeterministicIdentityFactory | None" = None
    ) -> ContextImage:  # type: ignore[name-defined]
        """Build a ``ContextImage`` with a deterministic or runtime identity."""
        image_id = factory.new_identity() if factory is not None else new_identity()
        return self.to_context_image(image_id)


def _solid_bytes(color: tuple[int, int, int], *, marker: str) -> bytes:
    """A tiny deterministic byte pattern that is stable but not a real image.

    The contract ``ContextImage`` only carries a hash and dimensions, and the
    editor contract validates mime type and dimensions rather than decoding
    bytes, so a stable byte pattern is sufficient for deterministic fixtures.
    The marker ensures each fixture's hash is distinct.
    """
    payload = marker.encode("ascii") + bytes(color)
    # Pad to a fixed size so the hash is stable and the fixture is non-trivial.
    payload += b"\x00" * max(0, 256 - len(payload))
    return payload


def default_preview_fixture() -> ImageFixture:
    """A stable preview-sized fixture for general composition scenarios."""
    raw = _solid_bytes((80, 110, 140), marker="preview-general")
    return ImageFixture(
        bytes_=raw,
        bytes_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
        width=480,
        height=640,
        mime_type="image/jpeg",
    )


def default_still_fixture() -> ImageFixture:
    """A stable high-resolution still fixture for Generated Visual Guidance."""
    raw = _solid_bytes((60, 90, 130), marker="still-accepted")
    return ImageFixture(
        bytes_=raw,
        bytes_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
        width=1920,
        height=1280,
        mime_type="image/jpeg",
    )
