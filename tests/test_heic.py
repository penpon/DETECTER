"""HEIC/HEIF images follow the same analysis path as JPEG/PNG/WebP."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from PIL import Image
from pillow_heif import from_pillow

from detecter.cli import collect_images, main
from detecter.core import (
    analyze_image,
    decoded_image,
    file_sha256,
    inspect_image,
    quantized_pixel_grid,
)


def make_heic(path: Path, size=(16, 8), *, orientation: int | None = None) -> None:
    """Create a minimal self-generated HEIC fixture (no third-party bytes)."""
    image = Image.new("RGB", size)
    pixels = image.load()
    assert pixels is not None
    for x in range(size[0]):
        for y in range(size[1]):
            pixels[x, y] = ((x * 13) % 256, (y * 21) % 256, (x * y) % 256)
    heif = from_pillow(image)
    if orientation is not None:
        exif = Image.Exif()
        exif[274] = orientation
        heif.info["exif"] = exif.tobytes()
    heif.save(path)


class HeicTests(unittest.TestCase):
    def test_inspect_reports_heif_and_original_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.heic"
            make_heic(path)
            media = inspect_image(path)
            self.assertEqual(media["format"], "HEIF")
            self.assertEqual(
                media["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
            )

    def test_analysis_uses_original_for_hash_and_c2pa(self):
        class Detector:
            def __init__(self):
                self.seen: list[tuple[int, int]] = []

            def score(self, path):
                with Image.open(path) as image:
                    self.seen.append(image.size)
                return 0.25

            def metadata(self):
                return {
                    "model": "ufd",
                    "model_version": "test",
                    "weights_version": "test",
                    "preprocessing_version": "test",
                }

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "oriented.heic"
            make_heic(path, orientation=6)
            before = path.read_bytes()
            detector = Detector()
            record = analyze_image(path, detector=detector)
            self.assertEqual(record["media"]["format"], "HEIF")
            self.assertEqual(record["media"]["sha256"], file_sha256(path))
            self.assertEqual(record["universal_fake_detect"]["status"], "ok")
            self.assertEqual(record["universal_fake_detect"]["raw_score"], 0.25)
            self.assertEqual(record["c2pa"]["status"], "absent")
            # libheif decodes the oriented pixels upright; the classifier
            # receives the displayed 8x16 image, not the stored 16x8 box.
            self.assertEqual(record["media"]["width"], 8)
            self.assertEqual(record["media"]["height"], 16)
            self.assertEqual(detector.seen, [(8, 16)])
            self.assertEqual(path.read_bytes(), before)

    def test_decoded_image_applies_exif_orientation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rotated.jpg"
            image = Image.new("RGB", (16, 8), "white")
            exif = Image.Exif()
            exif[274] = 6
            image.save(path, exif=exif)
            before = path.read_bytes()
            with decoded_image(path) as decoded:
                self.assertEqual(decoded.size, (8, 16))
                self.assertEqual(decoded.mode, "RGB")
            self.assertEqual(path.read_bytes(), before)

    def test_pixel_grid_accepts_heic(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.heic"
            make_heic(path)
            grid = quantized_pixel_grid(path)
            self.assertEqual((len(grid), len(grid[0]), len(grid[0][0])), (32, 32, 3))

    def test_corrupt_heic_is_a_reasoned_error_and_does_not_stop_others(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            broken = root / "broken.heic"
            broken.write_bytes(b"not a heic file" * 16)
            with self.assertRaisesRegex(ValueError, "読み込めません"):
                inspect_image(broken)
            valid = root / "valid.png"
            Image.new("RGB", (8, 8), "white").save(valid)
            output = root / "result.jsonl"
            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "analyze",
                        str(broken),
                        str(valid),
                        "--skip-ufd",
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(exit_code, 1)
            records = [
                json.loads(line)
                for line in output.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(records), 2)
            self.assertIn("error", records[0])
            self.assertNotIn("error", records[1])
            self.assertEqual(records[1]["media"]["format"], "PNG")

    def test_directory_collection_includes_heic_and_heif(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            heic = root / "a.heic"
            heif = root / "b.heif"
            make_heic(heic)
            make_heic(heif)
            (root / "ignore.txt").write_text("x", encoding="utf-8")
            found = {path.resolve() for path in collect_images([str(root)])}
            self.assertEqual(found, {heic.resolve(), heif.resolve()})


if __name__ == "__main__":
    unittest.main()
