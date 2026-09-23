from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from detecter.community_forensics import main


class CommunityForensicsTests(unittest.TestCase):
    def test_cli_records_cpu_measurement_without_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "image.png"
            Image.new("RGB", (40, 32), "white").save(path)
            output = io.StringIO()
            with (
                patch("detecter.community_forensics.infer", return_value=-1.25),
                redirect_stdout(output),
            ):
                code = main([str(path), "--image-id", "example", "--output", "-"])
            record = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(record["image_id"], "example")
            self.assertEqual(
                record["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
            )
            self.assertEqual(record["raw_score"], -1.25)
            self.assertEqual(record["status"], "ok")
            self.assertIsNone(record["error"])
            self.assertEqual(record["environment"]["device"], "cpu")
            self.assertIsInstance(
                record["environment"]["libraries"]["pillow-heif"], str
            )
            self.assertEqual(record["preprocessing"]["center_crop"], 384)
            for key in ("model_version", "weights_version", "preprocessing_version"):
                self.assertTrue(record[key])
            for key in ("label", "split", "source_group", "verdict", "probability"):
                self.assertNotIn(key, record)

    def test_cli_keeps_image_identity_and_failure_in_output_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "image.png"
            output = Path(temporary) / "measurement.json"
            Image.new("RGB", (32, 24), "white").save(path)
            for outcome in (
                OSError("weight download failed"),
                ValueError("weight load failed"),
                float("nan"),
            ):
                with self.subTest(outcome=outcome):
                    with patch(
                        "detecter.community_forensics.infer",
                        side_effect=outcome if isinstance(outcome, Exception) else None,
                        return_value=outcome,
                    ):
                        code = main(
                            [
                                str(path),
                                "--image-id",
                                "failed-image",
                                "--output",
                                str(output),
                            ]
                        )
                    record = json.loads(output.read_text())
                    self.assertEqual(code, 1)
                    self.assertEqual(record["status"], "error")
                    self.assertIsNone(record["raw_score"])
                    self.assertTrue(record["error"])
                    self.assertEqual(record["image_id"], "failed-image")
                    self.assertEqual(
                        record["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
                    )

    def test_cli_downloads_once_reuses_verified_cache_and_rejects_corruption(self):
        import torch

        from detecter.community_forensics import MODEL, WEIGHTS_REVISION

        model = Mock(return_value=torch.tensor([[2.5]]))
        model.eval.return_value = model
        libraries = {
            "timm": SimpleNamespace(create_model=Mock(return_value=model)),
            "safetensors": SimpleNamespace(),
            "safetensors.torch": SimpleNamespace(
                load_file=Mock(return_value={"vit.weight": torch.tensor([1.0])})
            ),
        }
        weights = b"fixed test weights"
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            path = Path(temporary) / "image.png"
            Image.new("RGB", (16, 24), "white").save(path)
            argv = [str(path), "--cache-dir", str(cache), "--output", "-"]
            with (
                patch.dict("sys.modules", libraries),
                patch(
                    "detecter.community_forensics.WEIGHTS_SHA256",
                    hashlib.sha256(weights).hexdigest(),
                ),
            ):
                output = io.StringIO()
                with (
                    patch("urllib.request.urlopen", return_value=io.BytesIO(weights)),
                    redirect_stdout(output),
                ):
                    self.assertEqual(main(argv), 0)
                self.assertEqual(json.loads(output.getvalue())["raw_score"], 2.5)
                with (
                    patch("urllib.request.urlopen", side_effect=OSError("offline")),
                    redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(main(argv), 0)
                (cache / MODEL / WEIGHTS_REVISION / "model.safetensors").write_bytes(
                    b"corrupted"
                )
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(argv), 1)
                self.assertIn("SHA-256", json.loads(output.getvalue())["error"])


if __name__ == "__main__":
    unittest.main()
