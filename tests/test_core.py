from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from detecter.cli import _create_jev_client, collect_images, main, run_jev_comparison
from detecter.core import (
    analyze_full_area_tiles,
    build_jev_state,
    create_derived_jpeg,
    inspect_image,
    provisional_verdict,
    quantized_pixel_grid,
    tile_bounds,
)


class CoreTests(unittest.TestCase):
    def test_verdict_prefers_trusted_ai_provenance(self):
        verdict = provisional_verdict(
            {
                "status": "present",
                "trusted": True,
                "confirmed": True,
                "generation_scope": "full",
                "ai_source_assertion": True,
            },
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

    def test_jev_compare_rejects_skip_ufd(self):
        with redirect_stdout(io.StringIO()):
            exit_code = main(
                [
                    "analyze",
                    "missing.png",
                    "--jev-compare",
                    "--skip-ufd",
                    "--output",
                    "-",
                ]
            )
        self.assertEqual(exit_code, 2)

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

    def test_tile_bounds_cover_every_pixel_without_more_than_64_tiles(self):
        width, height = 137, 91
        bounds = tile_bounds(width, height, tile_size=16)
        covered = {
            (x, y)
            for left, top, right, bottom in bounds
            for x in range(left, right)
            for y in range(top, bottom)
        }
        self.assertLessEqual(len(bounds), 64)
        self.assertEqual(len(covered), width * height)

    def test_pixel_grid_is_deterministic_and_quantized(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "sample.png"
            Image.new("RGB", (64, 32), (255, 128, 0)).save(image)
            first = quantized_pixel_grid(image)
            second = quantized_pixel_grid(image)
            self.assertEqual(first, second)
            self.assertTrue(
                all(
                    0 <= value <= 15
                    for row in first
                    for pixel in row
                    for value in pixel
                )
            )

    def test_jev_state_excludes_file_identity_and_diff_is_only_pixel_grid(self):
        media = {
            "format": "PNG",
            "width": 32,
            "height": 24,
            "mode": "RGB",
            "sha256": "secret",
        }
        state = build_jev_state(
            media,
            {"status": "absent"},
            {"status": "ok", "mean": 0.2},
            input_variant="original",
        )
        serialized = json.dumps(state)
        self.assertNotIn("secret", serialized)
        with_pixel_grid = json.loads(json.dumps(state))
        with_pixel_grid["pixel_grid"] = [[[0, 0, 0]]]
        without_grid = json.loads(json.dumps(with_pixel_grid))
        without_grid.pop("pixel_grid")
        self.assertEqual(without_grid, state)

    def test_full_area_tiles_are_batched_and_summarized(self):
        class Detector:
            def __init__(self):
                self.batches = []

            def score_images(self, images):
                self.batches.append(len(images))
                return [0.25] * len(images)

        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "sample.png"
            Image.new("RGB", (2048, 2048), "white").save(image)
            detector = Detector()
            result = analyze_full_area_tiles(image, detector)
            self.assertEqual(result["tile_count"], 64)
            self.assertEqual(detector.batches, [16, 16, 16, 16])
            self.assertEqual(result["above_threshold_count"], 0)

    def test_full_area_tiles_use_exif_transposed_dimensions(self):
        class Detector:
            def score_images(self, images):
                return [0.25] * len(images)

        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "rotated.jpg"
            exif = Image.Exif()
            exif[274] = 6
            Image.new("RGB", (16, 8), "white").save(image, exif=exif)
            result = analyze_full_area_tiles(
                image, Detector(), tile_size=8, max_tiles_per_axis=4
            )
            self.assertEqual((result["rows"], result["columns"]), (2, 1))
            self.assertEqual(
                [tile["bounds"] for tile in result["tiles"]],
                [[0, 0, 8, 8], [0, 8, 8, 16]],
            )

    def test_derived_jpeg_is_resized_and_temporary(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.png"
            Image.new("RGB", (2048, 1024), "white").save(source)
            derived = create_derived_jpeg(source, directory=Path(temporary))
            self.assertEqual(derived.suffix, ".jpg")
            with Image.open(derived) as image:
                self.assertEqual(image.size, (1024, 512))

    def test_jev_calls_continue_after_one_request_error(self):
        class Client:
            def __init__(self):
                self.calls = []

            def system_one(self, *, state, questions):
                self.calls.append((state, questions))
                if len(self.calls) == 1:
                    raise RuntimeError("network")
                return SimpleNamespace(
                    answers={
                        "ai_involvement": SimpleNamespace(
                            choice="inconclusive",
                            probabilities={
                                "ai_involvement_likely": 0.2,
                                "inconclusive": 0.6,
                                "no_ai_signal_detected": 0.2,
                            },
                            confidence=0.4,
                        )
                    },
                    model="jev-1.13.0",
                    usage=SimpleNamespace(input_tokens=10, output_tokens=2),
                    request_id="request-id",
                )

        client = Client()
        failed = False
        for _ in range(4):
            results, request_failed = run_jev_comparison(
                client,
                {"A": {"x": 1}, "B": {"x": 1, "pixel_grid": []}},
            )
            failed = failed or request_failed
            self.assertIn("A", results)
            self.assertIn("B", results)
        self.assertTrue(failed)
        self.assertEqual(len(client.calls), 8)
        self.assertEqual(results["B"]["choice"], "inconclusive")

    def test_jev_client_pins_model_and_disables_retries(self):
        import typesafe_sdk

        with patch.object(
            typesafe_sdk, "TypeSafeClient", return_value=object()
        ) as factory:
            _create_jev_client()
        self.assertEqual(factory.call_args.kwargs["model"], "jev-1.13.0")
        self.assertEqual(factory.call_args.kwargs["retry"].max_retries, 0)


if __name__ == "__main__":
    unittest.main()
