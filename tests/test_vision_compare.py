from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import httpx2
from PIL import Image

from detecter.core import inspect_image
from scripts.compare_diffusiongemma import compare, prepare_case


class VisionCompareTests(unittest.TestCase):
    def test_eight_calls_isolate_errors_and_strip_identity_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-camera-label.png"
            evidence = Path(directory) / "evidence.jsonl"
            exif = Image.Exif()
            exif[274] = 6
            exif[315] = "private-author"
            Image.new("RGB", (64, 48), "red").save(path, exif=exif)
            record = {
                "input_variant": "original",
                "media": inspect_image(path),
                "c2pa": {"status": "absent", "issuer": "private-author"},
                "universal_fake_detect_tiles": {"status": "ok", "mean": 0.1},
                "verdict": "private-local-verdict",
            }
            evidence.write_text(json.dumps(record))
            case = prepare_case(evidence, path)
            requests = []

            def handler(request):
                payload = json.loads(request.content)
                requests.append(payload)
                if len(requests) == 1:
                    return httpx2.Response(503, text="test-private-key")
                return httpx2.Response(
                    200,
                    json={
                        "model": "openjev-0.1",
                        "answers": {
                            "ai_involvement": {
                                "type": "choice",
                                "choice": "inconclusive",
                                "probabilities": {
                                    "ai_involvement_likely": 0.1,
                                    "inconclusive": 0.8,
                                    "no_ai_signal_detected": 0.1,
                                },
                                "confidence": 0.42,
                            }
                        },
                        "usage": {"input_tokens": 100, "output_tokens": 0},
                    },
                )

            output = io.StringIO()
            with (
                httpx2.Client(transport=httpx2.MockTransport(handler)) as client,
                redirect_stdout(io.StringIO()),
            ):
                code = compare(
                    client,
                    "https://example.test/v1/systemone",
                    "openjev-0.1",
                    [case] * 4,
                    output,
                )
            self.assertEqual(code, 1)
            self.assertEqual(len(requests), 8)
            results = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(results[0]["http_status"], 503)
            self.assertEqual(results[-1]["response"]["model"], "openjev-0.1")
            self.assertNotIn("test-private-key", output.getvalue())
            self.assertNotIn("data:image", output.getvalue())
            for request in requests:
                self.assertEqual(request["samples"], 1)
                self.assertEqual(request["model"], "openjev-0.1")
                text = json.dumps(request["state"])
                for secret in (
                    str(path),
                    path.name,
                    "private-author",
                    "private-local-verdict",
                    record["media"]["sha256"],
                ):
                    self.assertNotIn(secret, text)
                blob = base64.b64decode(request["images"][0].split(",")[1])
                with Image.open(io.BytesIO(blob)) as image:
                    self.assertEqual(image.size, (48, 64))
                    self.assertFalse(image.getexif())
            self.assertEqual(requests[0]["images"], requests[1]["images"])
            state_b = dict(requests[1]["state"])
            state_b.pop("forensics")
            self.assertEqual(requests[0]["state"], state_b)
            record["media"]["sha256"] = "changed"
            evidence.write_text(json.dumps(record))
            with self.assertRaises(StopIteration):
                prepare_case(evidence, path)
