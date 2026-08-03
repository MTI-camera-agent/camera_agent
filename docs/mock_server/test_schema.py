import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

try:
    from mock_server.protocol_schema import (
        ProtocolValidationError,
        SCHEMA,
        validate_message,
    )
except ModuleNotFoundError:
    from protocol_schema import ProtocolValidationError, SCHEMA, validate_message


class ProtocolSchemaTests(unittest.TestCase):
    def test_schema_is_valid_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(SCHEMA)

    def test_valid_result(self) -> None:
        result = {
            "type": "result",
            "version": 1,
            "messageId": "11111111-1111-4111-8111-111111111111",
            "observationId": 42,
            "timestampMs": 1000,
            "text": "Move left.",
            "overlays": [{
                "id": "guide",
                "kind": "line",
                "points": [{"x": 0.1, "y": 0.2}, {"x": 0.9, "y": 0.2}],
                "color": "#FFD340",
                "lineWidth": 3,
                "expiresInMilliseconds": 1500,
            }],
        }
        self.assertEqual(validate_message(result), result)

    def test_result_requires_metadata_and_content(self) -> None:
        with self.assertRaises(ProtocolValidationError):
            validate_message({
                "type": "result",
                "version": 1,
                "messageId": "11111111-1111-4111-8111-111111111111",
                "observationId": 42,
                "timestampMs": 1000,
            })

    def test_unknown_fields_are_rejected(self) -> None:
        with self.assertRaises(ProtocolValidationError):
            validate_message({
                "type": "capture_high_resolution",
                "version": 1,
                "requestId": "11111111-1111-4111-8111-111111111111",
                "priority": "high",
            })

    def test_overlay_ids_must_be_unique(self) -> None:
        with self.assertRaises(ProtocolValidationError):
            validate_message({
                "type": "result",
                "version": 1,
                "messageId": "11111111-1111-4111-8111-111111111111",
                "observationId": 42,
                "timestampMs": 1000,
                "overlays": [
                    {
                        "id": "duplicate",
                        "kind": "line",
                        "points": [{"x": 0, "y": 0}, {"x": 1, "y": 1}],
                    },
                    {
                        "id": "duplicate",
                        "kind": "circle",
                        "points": [{"x": 0.2, "y": 0.2}, {"x": 0.4, "y": 0.4}],
                    },
                ],
            })

    def test_desktop_guide_json_examples_match_schema(self) -> None:
        guide = (
            Path(__file__).resolve().parent.parent / "DESKTOP_AGENT_GUIDE.md"
        ).read_text(encoding="utf-8")
        examples = re.findall(r"```json\n(.*?)\n```", guide, flags=re.DOTALL)
        self.assertGreater(len(examples), 0)
        for example in examples:
            with self.subTest(message_type=json.loads(example).get("type")):
                message = json.loads(example)
                validate_message(message)
                Draft202012Validator(
                    SCHEMA,
                    format_checker=FormatChecker(),
                ).validate(message)


if __name__ == "__main__":
    unittest.main()
