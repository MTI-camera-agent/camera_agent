"""Dependency-free helpers for the HelloCamera protocol-v1 binary envelope."""

from __future__ import annotations

import json
import struct
import zlib
from typing import Any


def encode_binary(header: dict[str, Any], payload: bytes) -> bytes:
    encoded_header = json.dumps(header, separators=(",", ":"), sort_keys=True).encode()
    return struct.pack(">I", len(encoded_header)) + encoded_header + payload


def decode_binary(message: bytes) -> tuple[dict[str, Any], bytes]:
    if len(message) < 4:
        raise ValueError("binary message is shorter than its length prefix")
    (header_length,) = struct.unpack(">I", message[:4])
    end = 4 + header_length
    if header_length == 0 or end > len(message):
        raise ValueError("binary message has an invalid header length")
    return json.loads(message[4:end]), message[end:]


def reference_png(width: int = 360, height: int = 240) -> bytes:
    """Create a dependency-free RGB PNG containing a rule-of-thirds guide."""

    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            near_vertical = min(abs(x - width // 3), abs(x - 2 * width // 3)) < 2
            near_horizontal = min(abs(y - height // 3), abs(y - 2 * height // 3)) < 2
            if near_vertical or near_horizontal:
                rows.extend((255, 211, 64))
            else:
                rows.extend((25 + y * 25 // height, 54 + x * 45 // width, 86 + y * 55 // height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows), level=6))
        + chunk(b"IEND", b"")
    )
