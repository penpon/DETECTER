from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from PIL import Image

from detecter.ledger import main, read_ledger, split_ledger


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.ledger = self.root / "ledger.jsonl"

    def row(self, image_id="one", **changes):
        image = self.root / f"{image_id}.png"
        color = hashlib.sha256(image_id.encode()).digest()[:3]
        Image.new("RGB", (8, 6), tuple(color)).save(image)
        return {
            "image_id": image_id,
            "path": image.name,
            "source_group": image_id,
            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "source": "synthetic test image",
            "license": "CC0",
            "label": "real",
            "split": "unassigned",
            "history": [],
            **changes,
        }

    def write(self, rows):
        self.ledger.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    def test_read_resolves_paths_and_preserves_labels_and_processing(self):
        rows = [
            self.row(history=[{"operation": "HDR"}, {"operation": "denoise"}]),
            self.row("unknown", label="unknown"),
        ]
        self.write(rows)
        result = read_ledger(self.ledger)
        self.assertEqual(result[0]["path"], str(self.root / "one.png"))
        self.assertEqual(result[0]["label"], "real")
        self.assertEqual(result[0]["history"], rows[0]["history"])
        self.assertEqual(result[1]["label"], "unknown")

    def test_rejects_invalid_fields_and_hash_mismatches(self):
        valid = self.row()
        invalid = [
            {**valid, "label": "photo"},
            {**valid, "split": "test"},
            {**valid, "history": ["HDR"]},
            {**valid, "sha256": "A" * 64},
            {**valid, "sha256": "0" * 64},
            {**valid, "source": " "},
            {**valid, "license": ""},
            {**valid, "camera": 42},
            {key: value for key, value in valid.items() if key != "image_id"},
            [],
        ]
        for row in invalid:
            with self.subTest(row=row):
                self.write([row])
                with self.assertRaises(ValueError):
                    read_ledger(self.ledger)
        self.write([{**valid, "path": "missing.png"}])
        with self.assertRaisesRegex(ValueError, "missing|画像"):
            read_ledger(self.ledger)
        self.assertEqual(
            read_ledger(self.ledger, verify_files=False)[0]["image_id"], "one"
        )

    def test_rejects_duplicate_identity_and_inconsistent_source_groups(self):
        first = self.row(split="tuning")
        second = self.row("two")
        invalid_pairs = [
            [first, first],
            [first, {**first, "image_id": "duplicate"}],
            [
                first,
                {
                    **second,
                    "source_group": "one",
                    "label": "generated",
                    "split": "tuning",
                },
            ],
            [first, {**second, "source_group": "one", "split": "evaluation"}],
        ]
        for rows in invalid_pairs:
            with self.subTest(rows=rows):
                self.write(rows)
                with self.assertRaises(ValueError):
                    read_ledger(self.ledger)

    def test_derived_rows_keep_parent_hash_group_label_and_history(self):
        parent = self.row(history=[{"operation": "develop"}])
        derived = self.row(
            "derived",
            source_group="one",
            source_image_id="one",
            source_sha256=parent["sha256"],
            history=[{"operation": "develop"}, {"operation": "jpeg", "quality": 75}],
        )
        self.write([parent, derived])
        self.assertEqual(len(read_ledger(self.ledger)), 2)
        for change in (
            {"source_sha256": "0" * 64},
            {"source_group": "other"},
            {"history": []},
            {"source_image_id": "derived"},
        ):
            with self.subTest(change=change):
                self.write([parent, {**derived, **change}])
                with self.assertRaises(ValueError):
                    read_ledger(self.ledger)
        # A derived-only ledger can link to an external original by ID and hash.
        self.write([derived])
        self.assertEqual(read_ledger(self.ledger)[0]["source_sha256"], parent["sha256"])

    def test_split_is_order_independent_and_keeps_groups_and_holdouts(self):
        rows = [
            self.row("one", generator="held-generator", label="generated"),
            self.row("two", source_group="one", label="generated"),
            self.row("three", camera="held-camera"),
            self.row("four", label="unknown"),
            self.row("five", label="edited"),
        ]
        self.write(rows)
        loaded = read_ledger(self.ledger)
        result = split_ledger(
            loaded,
            seed=20260922,
            evaluation_fraction=0,
            holdout_generators=["held-generator"],
            holdout_cameras=["held-camera"],
        )
        self.assertEqual(
            {row["image_id"]: row["split"] for row in result},
            {
                "one": "evaluation",
                "two": "evaluation",
                "three": "evaluation",
                "four": "tuning",
                "five": "tuning",
            },
        )
        self.assertTrue(all(row["split"] == "unassigned" for row in loaded))
        self.assertEqual(
            next(row for row in result if row["image_id"] == "four")["label"], "unknown"
        )
        first = split_ledger(loaded, seed=123, evaluation_fraction=0.5)
        second = split_ledger(list(reversed(loaded)), seed=123, evaluation_fraction=0.5)
        self.assertEqual(first, second)
        evaluation_groups = {
            row["source_group"] for row in first if row["split"] == "evaluation"
        }
        self.assertEqual(len(evaluation_groups), 2)

    def test_cli_validates_splits_and_rejects_invalid_input_without_overwrite(self):
        self.write([self.row(), self.row("two", label="unknown")])
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["validate", str(self.ledger)]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["images"], 2)
        output = self.root / "nested" / "split.jsonl"
        arguments = ["split", str(self.ledger), "--seed", "7", "--output", str(output)]
        self.assertEqual(main(arguments), 0)
        result = read_ledger(output)
        self.assertEqual({row["split"] for row in result}, {"tuning", "evaluation"})
        original = output.read_bytes()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(arguments), 1)
            self.ledger.write_text("invalid JSON\n", encoding="utf-8")
            self.assertEqual(main(["validate", str(self.ledger)]), 1)
        self.assertEqual(output.read_bytes(), original)

    def test_split_rejects_unknown_holdouts_and_invalid_fraction(self):
        rows = [self.row(generator="generator-a", camera="camera-a")]
        cases: list[dict[str, Any]] = [
            {"holdout_generators": ["typo"]},
            {"holdout_cameras": ["typo"]},
            {"evaluation_fraction": float("nan")},
            {"evaluation_fraction": -0.1},
            {"evaluation_fraction": 1.1},
        ]
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ValueError):
                split_ledger(rows, seed=1, **options)

    def test_external_parent_references_cannot_disagree(self):
        first = self.row(
            "derived-a",
            source_image_id="external",
            source_sha256="1" * 64,
            history=[{"operation": "jpeg"}],
        )
        second = self.row(
            "derived-b",
            source_image_id="external",
            source_sha256="2" * 64,
            history=[{"operation": "jpeg"}],
        )
        self.write([first, second])
        with self.assertRaises(ValueError):
            read_ledger(self.ledger)


if __name__ == "__main__":
    unittest.main()
