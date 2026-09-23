import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from detecter.core import file_sha256
from detecter.ufd_batch import main, measure, measure_batch


class UfdBatchTests(unittest.TestCase):
    def test_cli_resolves_relative_image_path_and_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.png"
            Image.new("RGB", (8, 8), "white").save(image)
            ledger, output = root / "ledger.jsonl", root / "output.jsonl"
            ledger.write_text(
                json.dumps(
                    {
                        "image_id": "image",
                        "path": "image.png",
                        "sha256": file_sha256(image),
                        "label": "real",
                    }
                )
                + "\n"
            )
            with patch("detecter.ufd_batch.UfdDetector") as detector:
                detector.return_value.score.return_value = 0.25
                self.assertEqual(
                    main(["--ledger", str(ledger), "--output", str(output)]), 0
                )
            record = json.loads(output.read_text())
            self.assertEqual(record["status"], "ok")
            self.assertEqual(record["raw_score"], 0.25)
            self.assertNotIn("label", record)

    def test_batch_excludes_labels_and_keeps_failures(self):
        class Detector:
            def score(self, path):
                self.path = path
                return 0.25

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.png"
            Image.new("RGB", (16, 16), "white").save(path)
            row = {
                "image_id": "one",
                "path": str(path),
                "sha256": file_sha256(path),
                "label": "generated",
                "split": "evaluation",
                "generator": "secret",
            }
            detector = Detector()
            records = measure_batch(
                [
                    row,
                    {
                        **row,
                        "image_id": "missing",
                        "path": str(path.with_name("absent.png")),
                    },
                ],
                detector=detector,
            )
            self.assertEqual([r["status"] for r in records], ["ok", "error"])
            self.assertEqual(records[0]["raw_score"], 0.25)
            self.assertIsInstance(records[0]["environment"]["pillow_heif"], str)
            self.assertEqual(detector.path, path)
            self.assertNotIn("label", records[0])
            self.assertNotIn("generator", records[0])
            self.assertEqual(records[1]["sha256"], row["sha256"])
            mismatch = measure(
                path, image_id="one", expected_sha256="0" * 64, detector=detector
            )
            self.assertEqual(mismatch["status"], "error")
            self.assertIn("hash", mismatch["error"])

    def test_model_failure_is_isolated_and_tiles_have_separate_condition(self):
        class Detector:
            def score(self, path):
                raise RuntimeError("model failure")

            def score_images(self, images):
                return [0.75] * len(images)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.png"
            Image.new("RGB", (500, 400), "white").save(path)
            failed = measure(path, image_id="one", detector=Detector())
            tiled = measure(path, image_id="one", detector=Detector(), mode="tiles")
            self.assertEqual(failed["status"], "error")
            self.assertEqual(tiled["raw_score"], 0.75)
            self.assertEqual(tiled["preprocessing"]["tile_count"], 6)
            self.assertNotEqual(
                failed["preprocessing_version"], tiled["preprocessing_version"]
            )


if __name__ == "__main__":
    unittest.main()
