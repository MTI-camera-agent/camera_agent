import json
import struct
import unittest

try:
    from mock_server.wire_protocol import decode_binary, encode_binary, reference_png
except ModuleNotFoundError:
    from wire_protocol import decode_binary, encode_binary, reference_png


class BinaryEnvelopeTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        header = {"type": "preview_image", "messageId": "abc", "version": 1}
        payload = b"\xff\xd8camera-jpeg\xff\xd9"
        decoded_header, decoded_payload = decode_binary(encode_binary(header, payload))
        self.assertEqual(decoded_header, header)
        self.assertEqual(decoded_payload, payload)

    def test_rejects_bad_header_length(self) -> None:
        with self.assertRaises(ValueError):
            decode_binary(struct.pack(">I", 100) + b"{}")

    def test_reference_image_is_png(self) -> None:
        image = reference_png(12, 8)
        self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(b"IEND", image)


if __name__ == "__main__":
    unittest.main()
