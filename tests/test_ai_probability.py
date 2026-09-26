"""End-to-end tests for the fully-automatic `detecter analyze` pipeline.

Real-photo stand-ins are JPEGs with iPhone camera EXIF; AI-generated stand-ins
are PNG/JPEG files without provenance (the same way the suite fabricates
samples — real corpus photos never enter the repo). Passive model layers are
stubbed at the inference boundary; Jev is a fake client.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from detecter.ai_probability import analyze_image, device_category, main
from detecter.final_probability import JEV_MODEL


def make_photo(path: Path, *, model: str = "iPhone 13", make: str = "Apple") -> None:
    exif = Image.Exif()
    if make:
        exif[271] = make
    if model:
        exif[272] = model
    exif[36867] = "2026:09:01 12:00:00"
    Image.new("RGB", (64, 48), (120, 90, 60)).save(path, exif=exif)


def make_generated(path: Path) -> None:
    Image.new("RGB", (64, 64), (200, 30, 30)).save(path)


def jev_client(probability: float = 0.05, choice: str = "authentic_capture"):
    class Client:
        def __init__(self):
            self.calls = []

        def system_one(self, *, state, questions):
            self.calls.append((state, questions))
            return SimpleNamespace(
                answers={
                    "ai_involvement": SimpleNamespace(
                        choice=choice,
                        probabilities={
                            "ai_generated": probability,
                            "ai_edited": 0.0,
                            "authentic_capture": 1.0 - probability,
                            "inconclusive": 0.0,
                        },
                    ),
                    "evidence_conflict": SimpleNamespace(noul=0.0),
                    "confidence": SimpleNamespace(score=3.0, confidence=0.9),
                },
                model=JEV_MODEL,
                usage=SimpleNamespace(input_tokens=10, output_tokens=2),
            )

    return Client()


def stub_scores(cf: float, cure: float, ufd: float):
    """Patch the three passive inference boundaries at once.

    Scalars apply one score to every image; a ``dict`` keyed by file name
    maps each image to its own score.
    """
    from contextlib import ExitStack

    def pick(value):
        def select(path, **_ignored):
            if isinstance(value, dict):
                return value[Path(path).name]
            return value

        return select

    stack = ExitStack()
    for target, value in (
        ("detecter.community_forensics.infer", cf),
        ("detecter.cure.infer", cure),
    ):
        stack.enter_context(patch(target, create=True, side_effect=pick(value)))
    for target in (
        "detecter.community_forensics.load_model",
        "detecter.cure.load_model",
    ):
        stack.enter_context(patch(target, create=True, return_value=SimpleNamespace()))
    stack.enter_context(
        patch(
            "detecter.ai_probability.UfdDetector",
            return_value=SimpleNamespace(
                device="cpu",
                score=pick(ufd),
                metadata=lambda: {"model": "ufd"},
            ),
        )
    )
    return stack


class UnifiedSchemaTests(unittest.TestCase):
    def test_real_photo_pipeline_returns_low_probability(self):
        with tempfile.TemporaryDirectory() as directory:
            photo = Path(directory) / "iphone13.jpg"
            make_photo(photo)
            with stub_scores(-7.0, 0.05, 0.93):
                record = analyze_image(photo, jev_client=jev_client())
            self.assertEqual(record["media"]["format"], "JPEG")
            self.assertTrue(0.0 <= record["ai_probability"] <= 1.0)
            self.assertLess(record["ai_probability"], 0.5)
            self.assertRegex(record["ai_probability_percent"], r"^\d+\.\d%$")
            self.assertTrue(0.0 <= record["confidence"] <= 1.0)
            breakdown = record["breakdown"]
            self.assertEqual(breakdown["camera"]["model"], "iPhone 13")
            self.assertEqual(breakdown["device_category"], "smartphone")
            self.assertEqual(breakdown["raw_scores"]["community_forensics_384"], -7.0)
            self.assertEqual(breakdown["raw_scores"]["cure"], 0.05)
            self.assertEqual(breakdown["raw_scores"]["universal_fake_detect"], 0.93)
            self.assertEqual(breakdown["c2pa"]["status"], "absent")
            self.assertEqual(breakdown["jev"]["status"], "ok")
            self.assertIsNone(record["bypass"])

    def test_generated_image_pipeline_returns_high_probability(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "gpt-image.png"
            make_generated(image)
            client = jev_client(0.92, "ai_generated")
            with stub_scores(-3.0, 0.9, 0.65):
                record = analyze_image(image, jev_client=client)
            self.assertGreater(record["ai_probability"], 0.6)
            self.assertEqual(record["state"], "ai_generated")
            self.assertEqual(record["breakdown"]["device_category"], "unknown")
            self.assertEqual(len(client.calls), 1)
            # The Jev state stays sanitized: no path, hash, or free text.
            state = client.calls[0][0]
            self.assertNotIn(str(image), json.dumps(state))
            self.assertNotIn(record["sha256"], json.dumps(state))

    def test_default_verdict_uses_statistical_fusion(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "generated.png"
            make_generated(image)
            with stub_scores(-3.0, 0.9, 0.65):
                record = analyze_image(image, jev_client=None)
            fusion = record["breakdown"]["fusion"]
            self.assertEqual(record["state"], fusion["state"])
            self.assertIsNone(record["breakdown"]["jev"])
            self.assertIn(fusion["state"], {"ai_likely", "inconclusive"})
            self.assertIsNotNone(fusion["fusion"]["ranks"])

    def test_jev_flag_restores_jev_verdict(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "generated.png"
            make_generated(image)
            client = jev_client(0.92, "ai_generated")
            with stub_scores(-3.0, 0.9, 0.65):
                record = analyze_image(image, jev_client=client)
            self.assertEqual(record["state"], "ai_generated")
            self.assertEqual(record["breakdown"]["jev"]["status"], "ok")
            # The statistical fusion result is still recorded for ablation.
            self.assertIn(
                record["breakdown"]["fusion"]["state"],
                {"ai_likely", "inconclusive"},
            )

    def test_all_models_missing_is_inconclusive_not_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "photo.png"
            make_generated(image)
            with (
                patch(
                    "detecter.ai_probability._measure",
                    return_value={"status": "error", "raw_score": None, "error": "x"},
                ),
                patch(
                    "detecter.ai_probability._ufd_measure",
                    return_value={"status": "error", "raw_score": None, "error": "x"},
                ),
            ):
                record = analyze_image(image, jev_client=None)
            self.assertEqual(record["state"], "inconclusive")
            self.assertEqual(record["ai_probability"], 0.0)
            self.assertEqual(record["confidence"], 0.0)
            self.assertIsNone(record["breakdown"]["base_probability"])

    def test_deterministic_bypass_short_circuits_models(self):
        confirmed = {
            "confirmed": True,
            "ai_source_assertion": True,
            "status": "present",
            "generation_scope": "full",
        }
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "signed.png"
            make_generated(image)
            with (
                patch("detecter.ai_probability.inspect_c2pa", return_value=confirmed),
                patch("detecter.ai_probability._measure") as measure_spy,
            ):
                record = analyze_image(image, jev_client=None)
            self.assertEqual(record["ai_probability"], 1.0)
            self.assertEqual(record["ai_probability_percent"], "100.0%")
            self.assertEqual(record["state"], "ai_confirmed")
            self.assertEqual(record["bypass"]["basis"], "c2pa_ai_claim")
            measure_spy.assert_not_called()

    def test_verified_synthid_bypasses_to_one(self):
        detected = {
            "status": "linked",
            "state": "detected",
            "automatically_verified": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "synthid.png"
            make_generated(image)
            with patch(
                "detecter.synthid_manual.summarize_synthid",
                return_value=detected,
            ):
                record = analyze_image(
                    image, jev_client=None, synthid_records=[{"x": 1}]
                )
            self.assertEqual(record["ai_probability"], 1.0)
            self.assertEqual(record["bypass"]["basis"], "synthid_detected")


class DeviceCategoryTests(unittest.TestCase):
    def test_categories(self):
        def exif(make=None, model=None):
            camera = {}
            if make:
                camera["make"] = make
            if model:
                camera["model"] = model
            return {"camera": camera}

        self.assertEqual(device_category(exif("Apple", "iPhone XS")), "smartphone")
        self.assertEqual(device_category(exif("Google", "Pixel 8 Pro")), "smartphone")
        self.assertEqual(device_category(exif("SONY", "ILCE-7M4")), "camera")
        self.assertEqual(device_category(exif("Canon", "EOS R5")), "camera")
        self.assertEqual(
            device_category(exif("EPSON", "Perfection V39 Scanner")), "scanner"
        )
        self.assertEqual(device_category(exif()), "unknown")
        self.assertEqual(device_category({"status": "error"}), "unknown")


class CliTests(unittest.TestCase):
    def test_cli_outputs_one_json_per_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photo = root / "real.jpg"
            generated = root / "generated.png"
            make_photo(photo, model="iPhone 11 Pro")
            make_generated(generated)
            output = io.StringIO()
            with (
                stub_scores(
                    {"real.jpg": -6.0, "generated.png": -3.0},
                    {"real.jpg": 0.05, "generated.png": 0.9},
                    0.9,
                ),
                patch(
                    "detecter.ai_probability._create_jev_client",
                    side_effect=RuntimeError("no key"),
                ),
                redirect_stdout(output),
                redirect_stderr(io.StringIO()),
            ):
                code = main([str(root)])
            self.assertEqual(code, 0)
            lines = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(len(lines), 2)
            by_name = {Path(line["image_id"]).name: line for line in lines}
            self.assertIn("real.jpg", by_name)
            self.assertIn("generated.png", by_name)
            for line in lines:
                self.assertTrue(0.0 <= line["ai_probability"] <= 1.0)
                self.assertIsNotNone(line["ai_probability_percent"])
                self.assertIn("breakdown", line)
            self.assertLess(
                by_name["real.jpg"]["ai_probability"],
                by_name["generated.png"]["ai_probability"],
            )

    def test_cli_error_record_keeps_exit_code_one(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.jpg"
            output = io.StringIO()
            with (
                redirect_stdout(output),
                redirect_stderr(io.StringIO()),
            ):
                code = main([str(missing)])
            self.assertEqual(code, 1)
            record = json.loads(output.getvalue().splitlines()[-1])
            self.assertEqual(record["state"], "error")
            self.assertIsNone(record["ai_probability"])

    def test_cli_no_jev_flag_skips_client_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "gen.png"
            make_generated(image)
            output = io.StringIO()
            with (
                stub_scores(-3.0, 0.9, 0.65),
                patch("detecter.ai_probability._create_jev_client") as factory,
                redirect_stdout(output),
                redirect_stderr(io.StringIO()),
            ):
                code = main([str(image), "--no-jev"])
            self.assertEqual(code, 0)
            factory.assert_not_called()
            record = json.loads(output.getvalue().splitlines()[-1])
            self.assertEqual(record["state"], record["breakdown"]["fusion"]["state"])


if __name__ == "__main__":
    unittest.main()
