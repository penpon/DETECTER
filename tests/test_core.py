from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from PIL import Image

from detecter.cli import collect_images, main
from detecter.core import inspect_image, provisional_verdict


class CoreTests(unittest.TestCase):
    def test_verdict_prefers_trusted_ai_provenance(self):
        verdict = provisional_verdict(
            {"status": "present", "trusted": True, "ai_source_assertion": True},
            {"status": "ok", "predicted_ai": False},
        )
        self.assertEqual(verdict["state"], "ai_evidence_confirmed")

    def test_untrusted_non_ai_provenance_does_not_signal_ai(self):
        verdict = provisional_verdict(
            {"status": "present", "trusted": False, "ai_source_assertion": False},
            {"status": "ok", "predicted_ai": False},
        )
        self.assertEqual(verdict["state"], "no_ai_signal_detected")

    def test_untrusted_ai_provenance_is_only_likely(self):
        verdict = provisional_verdict(
            {"status": "present", "trusted": False, "ai_source_assertion": True},
            {"status": "ok", "predicted_ai": False},
        )
        self.assertEqual(verdict["state"], "ai_likely")

    def test_invalid_manifest_is_inconclusive_even_with_ai_assertion(self):
        verdict = provisional_verdict(
            {
                "status": "present",
                "validation_state": "Invalid",
                "ai_source_assertion": True,
            },
            {"status": "ok", "predicted_ai": False},
        )
        self.assertEqual(verdict["state"], "inconclusive")

    def test_cli_records_c2pa_only_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "sample.png"
            output = root / "result.jsonl"
            Image.new("RGB", (32, 24), "white").save(image)

            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "analyze",
                        str(image),
                        "--skip-ufd",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(exit_code, 0)
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(record["media"]["format"], "PNG")
            self.assertEqual(record["c2pa"]["status"], "absent")
            self.assertEqual(record["verdict"]["state"], "inconclusive")

    def test_directory_collection_is_recursive_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "nested"
            nested.mkdir()
            image = nested / "sample.jpg"
            Image.new("RGB", (8, 8), "black").save(image)
            (nested / "ignore.txt").write_text("x", encoding="utf-8")
            found = collect_images([str(root), str(image)])
            self.assertEqual([path.resolve() for path in found], [image.resolve()])

    def test_input_size_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "sample.png"
            Image.new("RGB", (8, 8), "black").save(image)
            with self.assertRaisesRegex(ValueError, "上限"):
                inspect_image(image, max_bytes=1)


if __name__ == "__main__":
    unittest.main()
