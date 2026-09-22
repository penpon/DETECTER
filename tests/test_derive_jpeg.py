from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from PIL import Image

from detecter.derive_jpeg import derive_images, main
from detecter.ledger import read_ledger


class DeriveJpegTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.ledger = self.root / "ledger.jsonl"

    def image_row(
        self, name, label="real", size=(24, 16), *, orientation=None, mode="RGB"
    ):
        image = Image.new("RGB", size)
        image.putdata(
            [
                ((x * 13 + len(name)) % 256, (y * 21) % 256, (x * y) % 256)
                for y in range(size[1])
                for x in range(size[0])
            ]
        )
        image = image.convert(mode)
        path = self.root / f"{name}.png"
        exif = Image.Exif()
        if orientation is not None:
            exif[274] = orientation
            exif[315] = "private-test-author"
        if orientation is None:
            image.save(path)
        else:
            image.save(path, exif=exif)
        return {
            "image_id": name,
            "path": str(path),
            "source_group": name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source": "synthetic test image",
            "license": "CC0",
            "label": label,
            "split": "evaluation",
            "history": [{"operation": "develop"}],
        }

    def write_ledger(self, rows, path=None):
        path = path or self.ledger
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    def test_quality_conditions_preserve_originals_labels_and_exif_orientation(self):
        rows = [
            self.image_row("real", orientation=6),
            self.image_row("generated", "generated", mode="RGBA"),
            self.image_row("edited", "edited", mode="L"),
        ]
        original_bytes = {row["path"]: Path(row["path"]).read_bytes() for row in rows}
        self.write_ledger(rows)
        derived, conditions = derive_images(
            self.ledger, self.root / "images", long_sides=()
        )
        self.assertEqual(len(derived), 9)
        self.assertEqual(len(conditions), 9)
        by_source = {row["image_id"]: row for row in rows}
        for row in derived:
            parent = by_source[row["source_image_id"]]
            self.assertEqual(row["source_sha256"], parent["sha256"])
            for field in ("source_group", "split", "label"):
                self.assertEqual(row[field], parent[field])
            self.assertEqual(row["history"][:-1], parent["history"])
            transform = row["history"][-1]
            self.assertIn(transform["jpeg_quality"], [95, 85, 75])
            self.assertIsNone(transform["long_side"])
            with Image.open(row["path"]) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(
                    image.size, (16, 24) if parent["image_id"] == "real" else (24, 16)
                )
                self.assertFalse(image.getexif())
        for path, content in original_bytes.items():
            self.assertEqual(Path(path).read_bytes(), content)
        output = self.root / "derived.jsonl"
        self.write_ledger(derived, output)
        self.assertEqual(len(read_ledger(output)), 9)

    def test_resize_conditions_never_upscale_or_duplicate_original_hashes(self):
        rows = [self.image_row("small"), self.image_row("large", size=(1200, 600))]
        self.write_ledger(rows)
        derived, conditions = derive_images(
            self.ledger, self.root / "resized", qualities=()
        )
        self.assertEqual(len(conditions), 4)
        self.assertEqual(len(derived), 2)
        for result in conditions:
            transform = result["condition"]
            self.assertIsNone(transform["jpeg_quality"])
            self.assertEqual(transform["format"], "PNG")
            self.assertEqual(transform["interpolation"], "LANCZOS")
            if result["source_image_id"] == "small":
                self.assertEqual(result["status"], "unchanged")
                self.assertEqual(result["image_id"], "small")
                self.assertEqual(transform["output_size"], [24, 16])
            else:
                self.assertEqual(result["status"], "created")
        self.assertEqual(
            {tuple(row["history"][-1]["output_size"]) for row in derived},
            {(1024, 512), (512, 256)},
        )
        combined = self.root / "combined.jsonl"
        self.write_ledger([*rows, *derived], combined)
        self.assertEqual(len(read_ledger(combined)), 4)

    def test_cli_keeps_all_requested_conditions_when_outputs_are_identical(self):
        self.write_ledger([self.image_row("rotated", orientation=6)])
        output = self.root / "derived.jsonl"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(
                main(["--ledger", str(self.ledger), "--output", str(output)]), 0
            )
        derived = read_ledger(output)
        conditions_path = output.with_suffix(".conditions.jsonl")
        conditions = [
            json.loads(line) for line in conditions_path.read_text().splitlines()
        ]
        self.assertEqual(len(conditions), 5)
        self.assertEqual(len(derived), 4)
        resize = [
            item for item in conditions if item["condition"]["operation"] == "resize"
        ]
        self.assertEqual([item["status"] for item in resize], ["created", "duplicate"])
        self.assertEqual(resize[0]["image_id"], resize[1]["image_id"])
        original = output.read_bytes()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(
                main(["--ledger", str(self.ledger), "--output", str(output)]), 1
            )
        self.assertEqual(output.read_bytes(), original)

    def test_rejects_unsupported_or_repeated_conditions_before_creating_output(self):
        self.write_ledger([self.image_row("source")])
        for qualities, long_sides in (
            ([0], [1024]),
            ([101], []),
            ([True], []),
            ([95, 95], []),
            ([], [0]),
            ([], [True]),
            ([], []),
        ):
            with self.subTest(qualities=qualities, long_sides=long_sides):
                directory = self.root / "invalid"
                with self.assertRaises(ValueError):
                    derive_images(
                        self.ledger,
                        directory,
                        qualities=qualities,
                        long_sides=long_sides,
                    )
                self.assertFalse(directory.exists())

    def test_generated_bytes_and_condition_records_are_reproducible(self):
        self.write_ledger([self.image_row("source", orientation=6)])
        first, first_conditions = derive_images(self.ledger, self.root / "first")
        second, second_conditions = derive_images(self.ledger, self.root / "second")
        self.assertEqual(first_conditions, second_conditions)
        self.assertEqual(
            [row["sha256"] for row in first], [row["sha256"] for row in second]
        )

    def test_matching_outputs_from_different_source_groups_are_rejected(self):
        rows = [self.image_row("first"), self.image_row("second", "generated")]
        for index, row in enumerate(rows):
            image = Image.new("RGB", (16, 16), "white")
            exif = Image.Exif()
            exif[315] = str(index)
            image.save(row["path"], exif=exif)
            row["sha256"] = hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest()
        self.write_ledger(rows)
        with self.assertRaisesRegex(ValueError, "グループ"):
            derive_images(
                self.ledger, self.root / "collision", qualities=(95,), long_sides=()
            )


if __name__ == "__main__":
    unittest.main()
