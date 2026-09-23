from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from detecter.core import file_sha256
from detecter.cure import (
    ADAPTER_SHA256,
    BASE_FILENAME,
    BASE_REPO_ID,
    BASE_REVISION,
    BASE_SHA256,
    MODEL,
    SOURCE_COMMIT,
    main,
)


class CureTests(unittest.TestCase):
    def test_cli_records_cpu_measurement_without_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "image.png"
            Image.new("RGB", (40, 32), "white").save(path)
            output = io.StringIO()
            with (
                patch("detecter.cure.infer", return_value=0.75),
                redirect_stdout(output),
            ):
                code = main([str(path), "--image-id", "example", "--output", "-"])
            record = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(record["image_id"], "example")
            self.assertEqual(record["model"], MODEL)
            self.assertEqual(
                record["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
            )
            self.assertEqual(record["raw_score"], 0.75)
            self.assertEqual(record["status"], "ok")
            self.assertIsNone(record["error"])
            self.assertEqual(record["environment"]["device"], "cpu")
            self.assertEqual(record["model_version"], SOURCE_COMMIT)
            self.assertIn(ADAPTER_SHA256, record["weights_version"])
            self.assertIn(BASE_REVISION, record["weights_version"])
            self.assertIn(BASE_SHA256, record["weights_version"])
            self.assertTrue(record["preprocessing_version"])
            self.assertEqual(record["preprocessing"]["resize"], [336, 336])
            for key in ("label", "split", "verdict", "probability", "prediction"):
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
                        "detecter.cure.infer",
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

    def test_adapter_downloads_once_reuses_verified_cache_and_rejects_corruption(self):
        from detecter.cure import SOURCE_COMMIT, adapter_path

        weights = b"fixed test adapter"
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            with patch(
                "detecter.cure.ADAPTER_SHA256",
                hashlib.sha256(weights).hexdigest(),
            ):
                with patch("urllib.request.urlopen", return_value=io.BytesIO(weights)):
                    first = adapter_path(cache)
                self.assertTrue(first.is_file())
                self.assertEqual(
                    first, cache / MODEL / SOURCE_COMMIT / "cure_adapter.pt"
                )
                with patch("urllib.request.urlopen", side_effect=OSError("offline")):
                    second = adapter_path(cache)
                self.assertEqual(first, second)
                first.write_bytes(b"corrupted")
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    adapter_path(cache)

    def test_base_checkpoint_is_pinned_hashed_and_uses_configured_cache(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from detecter.cure import _resolve_base_checkpoint

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "base.pt"
            checkpoint.touch()
            cache = root / "cache"
            download = Mock(return_value=checkpoint)
            with (
                patch("detecter.cure.file_sha256", return_value=BASE_SHA256),
                patch.dict(
                    "sys.modules",
                    {"huggingface_hub": SimpleNamespace(hf_hub_download=download)},
                ),
            ):
                resolved = _resolve_base_checkpoint(cache_dir=cache)
            self.assertEqual(resolved, checkpoint)
            download.assert_called_once_with(
                BASE_REPO_ID,
                BASE_FILENAME,
                revision=BASE_REVISION,
                cache_dir=str(cache / MODEL / SOURCE_COMMIT),
            )

    def test_base_checkpoint_rejects_an_unpinned_hash(self):
        from detecter.cure import _resolve_base_checkpoint

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "base.pt"
            checkpoint.touch()
            with (
                patch("detecter.cure.file_sha256", return_value="0" * 64),
                self.assertRaisesRegex(ValueError, "基盤重みのSHA-256"),
            ):
                _resolve_base_checkpoint(checkpoint)

    def test_comparison_adds_cure_without_combining_scores(self):
        from detecter.comparison import compare_records

        class Detector:
            def score(self, path):
                return 0.7

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.png"
            Image.new("RGB", (8, 16), "white").save(image)
            inputs = [
                {
                    "image_id": "a",
                    "path": image,
                    "sha256": file_sha256(image),
                    "label": "generated",
                    "history": [{"quality": 75}],
                }
            ]
            with (
                patch("detecter.community_forensics.infer", return_value=-1.5),
                patch("detecter.cure.infer", return_value=0.9),
            ):
                records = compare_records(
                    inputs,
                    ufd_detector=Detector(),
                    community_model=object(),
                    cure_model=object(),
                    models=("community-forensics", "ufd", "cure"),
                )
            self.assertEqual(len(records), 3)
            by_model = {r["model"]: r for r in records}
            self.assertEqual(by_model["ufd"]["raw_score"], 0.7)
            self.assertEqual(by_model["community-forensics-384"]["raw_score"], -1.5)
            self.assertEqual(by_model["cure"]["raw_score"], 0.9)
            self.assertTrue(all(r["status"] == "ok" for r in records))
            self.assertEqual({r["sha256"] for r in records}, {inputs[0]["sha256"]})
            self.assertEqual({r["source_image_id"] for r in records}, {"a"})
            versions = {r["preprocessing_version"] for r in records}
            self.assertEqual(len(versions), 3)
            self.assertTrue(
                all(
                    r["history"] == [{"quality": 75}] and "label" not in r
                    for r in records
                )
            )
            mismatched = [{**inputs[0], "sha256": "0" * 64}]
            with (
                patch("detecter.community_forensics.infer") as cf_infer,
                patch("detecter.cure.infer") as cure_infer,
            ):
                records = compare_records(
                    mismatched,
                    ufd_detector=Detector(),
                    community_model=object(),
                    cure_model=object(),
                    models=("community-forensics", "ufd", "cure"),
                )
                cf_infer.assert_not_called()
                cure_infer.assert_not_called()
            self.assertTrue(all(r["status"] == "error" for r in records))

    def test_default_comparison_stays_two_models(self):
        from detecter.comparison import compare_records

        class Detector:
            def score(self, path):
                return 0.7

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.png"
            Image.new("RGB", (8, 8), "white").save(image)
            inputs = [
                {
                    "image_id": "a",
                    "path": image,
                    "sha256": file_sha256(image),
                }
            ]
            with patch("detecter.community_forensics.infer", return_value=-1.5):
                records = compare_records(
                    inputs, ufd_detector=Detector(), community_model=object()
                )
            self.assertEqual(len(records), 2)
            self.assertEqual(
                {r["model"] for r in records}, {"ufd", "community-forensics-384"}
            )


if __name__ == "__main__":
    unittest.main()
