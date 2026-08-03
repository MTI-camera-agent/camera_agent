from __future__ import annotations

import json
import struct

import pytest

from camera_agent.protocol import (
    ObservationAssembler,
    ProtocolError,
    decode_binary,
    encode_binary,
    make_result,
    validate_message,
)
from tests.helpers import JPEG, observation_message, preview_header


def test_binary_round_trip_and_header_guard() -> None:
    observation = observation_message()
    header = preview_header(observation)
    decoded_header, decoded_payload = decode_binary(encode_binary(header, JPEG))
    assert decoded_header == header
    assert decoded_payload == JPEG
    with pytest.raises(ProtocolError):
        decode_binary(struct.pack(">I", 70_000) + b"{}")


def test_assembler_correlates_interleaved_pairs_by_both_ids() -> None:
    assembler = ObservationAssembler()
    first = observation_message(1)
    second = observation_message(2)
    assert assembler.add_metadata(first) is None
    assert assembler.add_metadata(second) is None
    assembled_second = assembler.add_preview(preview_header(second), JPEG)
    assembled_first = assembler.add_preview(preview_header(first), JPEG)
    assert assembled_second and assembled_second.observation_id == 2
    assert assembled_first and assembled_first.observation_id == 1


def test_assembler_rejects_observation_id_mismatch() -> None:
    assembler = ObservationAssembler()
    observation = observation_message(1)
    assembler.add_metadata(observation)
    header = preview_header(observation)
    header["observationId"] = 2
    with pytest.raises(ProtocolError):
        assembler.add_preview(header, JPEG)


def test_strict_result_validation() -> None:
    result = make_result(1, text="Move left.")
    assert validate_message(result) == result
    invalid = json.loads(json.dumps(result))
    invalid["surprise"] = True
    with pytest.raises(ProtocolError):
        validate_message(invalid)

