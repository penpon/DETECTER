import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from detecter.comparison import compare_records, main
from detecter.core import file_sha256


class ComparisonTests(unittest.TestCase):
    def test_comparison_keeps_identity_conditions_and_one_sided_failures(self):
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
            with patch(
                "detecter.community_forensics.infer",
                side_effect=RuntimeError("model failed"),
            ):
                records = compare_records(
                    inputs, ufd_detector=Detector(), community_model=object()
                )
            self.assertEqual(len(records), 2)
            by_model = {r["model"]: r for r in records}
            self.assertEqual(by_model["ufd"]["status"], "ok")
            self.assertEqual(by_model["community-forensics-384"]["status"], "error")
            self.assertEqual({r["sha256"] for r in records}, {inputs[0]["sha256"]})
            self.assertEqual({r["source_image_id"] for r in records}, {"a"})
            self.assertNotEqual(
                records[0]["preprocessing_version"], records[1]["preprocessing_version"]
            )
            self.assertTrue(
                all(
                    r["history"] == [{"quality": 75}] and "label" not in r
                    for r in records
                )
            )
            mismatched = [{**inputs[0], "sha256": "0" * 64}]
            with patch("detecter.community_forensics.infer") as infer:
                records = compare_records(
                    mismatched, ufd_detector=Detector(), community_model=object()
                )
                infer.assert_not_called()
            self.assertTrue(all(r["status"] == "error" for r in records))

    def test_cli_order_is_stable_and_keeps_two_records_per_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = []
            for name, color in [("b", "white"), ("a", "black")]:
                image = root / f"{name}.png"
                Image.new("RGB", (8, 8), color).save(image)
                rows.append(
                    {"image_id": name, "path": image.name, "sha256": file_sha256(image)}
                )
            ledger = root / "ledger.jsonl"
            results = []
            for index, items in enumerate((rows, list(reversed(rows)))):
                ledger.write_text("".join(json.dumps(row) + "\n" for row in items))
                output = root / f"{index}.jsonl"
                with (
                    patch("detecter.comparison.UfdDetector") as ufd,
                    patch("detecter.comparison.cf.load_model", return_value=object()),
                    patch("detecter.community_forensics.infer", return_value=-1.5),
                ):
                    ufd.return_value.score.return_value = 0.25
                    self.assertEqual(
                        main(
                            [
                                "community-forensics",
                                "ufd",
                                "--ledger",
                                str(ledger),
                                "--output",
                                str(output),
                            ]
                        ),
                        0,
                    )
                results.append(
                    [json.loads(line) for line in output.read_text().splitlines()]
                )
            self.assertEqual(
                [(r["image_id"], r["model"], r["raw_score"]) for r in results[0]],
                [(r["image_id"], r["model"], r["raw_score"]) for r in results[1]],
            )
            self.assertEqual(len(results[0]), 4)


if __name__ == "__main__":
    unittest.main()
