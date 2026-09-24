from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from detecter.core import file_sha256
from detecter.openai_provenance import (
    aggregate,
    classify_condition,
    generator_name,
    measure,
    request_openai_provenance,
    summarize_openai_response,
)


class OpenAIProvenanceTests(unittest.TestCase):
    def test_summarize_openai_response_extracts_c2pa_and_synthid(self):
        response = {
            "object": "content_provenance_check",
            "created_at": 1778000000,
            "results": [
                {
                    "type": "c2pa",
                    "outcome": "detected",
                    "validation_state": "trusted",
                    "issuer": "OpenAI OpCo, LLC",
                    "model": "gpt-image",
                    "generated_at": "2026-07-27T18:34:12Z",
                },
                {
                    "type": "synthid",
                    "outcome": "not_detected",
                    "model": None,
                    "generated_at": None,
                },
            ],
        }
        summary = summarize_openai_response(response)
        self.assertEqual(summary["c2pa"]["outcome"], "detected")
        self.assertEqual(summary["c2pa"]["validation_state"], "trusted")
        self.assertEqual(summary["c2pa"]["model"], "gpt-image")
        self.assertEqual(summary["synthid"]["outcome"], "not_detected")

    def test_summarize_missing_results_defaults_to_not_detected(self):
        summary = summarize_openai_response({"object": "content_provenance_check"})
        self.assertEqual(summary["c2pa"]["outcome"], "not_detected")
        self.assertEqual(summary["synthid"]["outcome"], "not_detected")

    def test_classify_condition(self):
        self.assertEqual(classify_condition([]), "original")
        self.assertEqual(
            classify_condition(
                [
                    {"operation": "resize", "long_side": 1024},
                    {"operation": "jpeg", "jpeg_quality": 75},
                ]
            ),
            "sns-q75",
        )
        self.assertEqual(
            classify_condition([{"operation": "jpeg", "jpeg_quality": 95}]),
            "jpeg95",
        )
        self.assertEqual(
            classify_condition([{"name": "sofakediffusion-v1"}]),
            "sofakediffusion-v1",
        )

    def test_generator_name_inference(self):
        self.assertEqual(
            generator_name({"path": "/x/gpt-image-2-001.png"}), "gpt-image-2"
        )
        self.assertEqual(
            generator_name({"path": "/x/nano-banana-001.png"}), "nano-banana"
        )
        self.assertEqual(generator_name({"path": "/x/IMG_7608.PNG"}), "iphone-real")
        self.assertEqual(
            generator_name({"generator": "manual", "path": "/x/foo.png"}), "manual"
        )

    def test_aggregate_counts_by_generator_and_condition(self):
        records = [
            {
                "generator": "gpt-image-2",
                "condition": "original",
                "openai": {
                    "c2pa": {"outcome": "detected"},
                    "synthid": {"outcome": "detected"},
                },
            },
            {
                "generator": "gpt-image-2",
                "condition": "original",
                "openai": {
                    "c2pa": {"outcome": "not_detected"},
                    "synthid": {"outcome": "not_detected"},
                },
            },
            {
                "generator": "iphone-real",
                "condition": "sns-q75",
                "openai": None,
                "local_c2pa": {"status": "present", "ai_source_assertion": True},
            },
        ]
        summary = aggregate(records)
        rows = {f"{r['generator']}|{r['condition']}": r for r in summary["rows"]}
        self.assertEqual(rows["gpt-image-2|original"]["c2pa_detected"], 1)
        self.assertEqual(rows["gpt-image-2|original"]["synthid_detected"], 1)
        self.assertEqual(rows["iphone-real|sns-q75"]["local_c2pa_detected"], 1)
        self.assertEqual(summary["total"], 3)

    def test_measure_api_key_missing_with_local_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "plain.png"
            Image.new("RGB", (8, 8), "red").save(image)
            with patch.dict(os.environ, {}, clear=True):
                record = measure(image, image_id="plain-001", local_fallback=True)
            self.assertEqual(record["status"], "local_fallback")
            self.assertEqual(record["api_status"], "api_key_missing")
            self.assertIsNotNone(record["local_c2pa"])
            self.assertEqual(record["sha256"], file_sha256(image))

    def test_measure_api_key_missing_without_fallback_is_error(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "plain.png"
            Image.new("RGB", (8, 8), "blue").save(image)
            with patch.dict(os.environ, {}, clear=True):
                record = measure(image, image_id="plain-002", local_fallback=False)
            self.assertEqual(record["status"], "error")
            self.assertIn("OPENAI_API_KEY", record["error"])

    def test_request_openai_provenance_rejects_unsupported_format(self):
        with tempfile.TemporaryDirectory() as directory:
            unsupported = Path(directory) / "note.txt"
            unsupported.write_text("not an image", encoding="utf-8")
            result = request_openai_provenance(unsupported, api_key="fake-key")
            self.assertEqual(result["api_status"], "unsupported_format")


if __name__ == "__main__":
    unittest.main()
