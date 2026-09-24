"""The evaluation cohort builder verifies identity and records its gaps."""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pillow_heif import from_pillow

from detecter.cohort import (
    build_ledger,
    coverage_report,
    main,
    read_inventory,
    scan_directory,
)


def make_photo(
    path: Path,
    *,
    model: str = "",
    make: str = "Apple",
    size: tuple[int, int] = (8, 8),
    image: Image.Image | None = None,
    format: str | None = None,
) -> None:
    exif = Image.Exif()
    if model:
        exif[271] = make
        exif[272] = model
    if image is None:
        image = Image.new("RGB", size)
        pixels = image.load()
        assert pixels is not None
        rng = random.Random(str(size))
        for x in range(size[0]):
            for y in range(size[1]):
                pixels[x, y] = (
                    rng.randrange(256),
                    rng.randrange(256),
                    rng.randrange(256),
                )
    image.save(path, format=format, exif=exif)


def make_heic_photo(path: Path, *, model: str = "iPhone 13") -> None:
    exif = Image.Exif()
    exif[271] = "Apple"
    exif[272] = model
    heif = from_pillow(Image.new("RGB", (8, 8), "gray"))
    heif.info["exif"] = exif.tobytes()
    heif.save(path)


def manifest(entries: list[dict], requirements: dict) -> dict:
    return {"sources": entries, "requirements": requirements}


class CohortTests(unittest.TestCase):
    def test_scan_directory_records_only_verifiable_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_photo(root / "photo.jpg", model="iPhone 13")
            make_photo(root / "no-camera.jpg", model="")
            rows = scan_directory(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["model"], "iPhone 13")
            self.assertEqual(rows[0]["format"], "JPEG")
            self.assertEqual(len(rows[0]["sha256"]), 64)

    def test_same_photo_in_two_encodings_shares_one_source_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = root / "images"
            images.mkdir()
            rng = random.Random("photo")
            levels = [
                [rng.choice((30, 90, 150, 210, 250)) for _ in range(8)]
                for _ in range(8)
            ]
            photo = Image.new("RGB", (64, 48))
            pixels = photo.load()
            assert pixels is not None
            for x in range(64):
                for y in range(48):
                    value = levels[y // 6][x // 8]
                    pixels[x, y] = (value, value, value)
            other = Image.new("RGB", (64, 48), "white")
            make_photo(images / "a.png", model="iPhone 13", image=photo)
            make_photo(images / "b.jpg", model="iPhone 13", image=photo)
            make_photo(images / "c.jpg", model="iPhone 13", image=other)
            value = manifest(
                [
                    {
                        "root": str(images),
                        "label": "real",
                        "source": "所有者による撮影",
                        "license": "評価利用のみ",
                        "id_prefix": "real",
                        "inventory": str(_inventory(images, root, "images.jsonl")),
                    }
                ],
                {"minimum_real_groups": 1},
            )
            rows, _ = build_ledger(value, base=root)
            groups = {Path(row["path"]).name: row["source_group"] for row in rows}
            self.assertEqual(len(rows), 3)
            self.assertEqual(groups["a.png"], groups["b.jpg"])
            self.assertNotEqual(groups["a.png"], groups["c.jpg"])
            self.assertEqual(len({row["source_group"] for row in rows}), 2)

    def test_scan_directory_can_limit_the_formats(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_photo(root / "photo.jpg", model="iPhone 13")
            make_heic_photo(root / "photo.heic")
            self.assertEqual(
                [Path(row["path"]).suffix for row in scan_directory(root)],
                [".heic", ".jpg"],
            )
            only_heic = scan_directory(root, suffixes=["heic"])
            self.assertEqual(len(only_heic), 1)
            self.assertEqual(only_heic[0]["format"], "HEIF")

    def test_scan_directory_keeps_unlabelled_images_when_allowed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_photo(root / "no-camera.jpg", model="")
            self.assertEqual(len(scan_directory(root, require_camera=False)), 1)

    def test_build_ledger_registers_camera_generator_history_and_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_root = root / "real"
            generated_root = root / "generated"
            real_root.mkdir()
            generated_root.mkdir()
            make_photo(real_root / "a.jpg", model="iPhone 13")
            make_photo(generated_root / "b.png", model="")
            (generated_root / "duplicate.png").write_bytes(
                (generated_root / "b.png").read_bytes()
            )
            value = manifest(
                [
                    {
                        "root": str(real_root),
                        "label": "real",
                        "source": "所有者による撮影",
                        "license": "評価利用のみ",
                        "id_prefix": "real",
                        "inventory": str(_inventory(real_root, root, "real.jsonl")),
                    },
                    {
                        "root": str(generated_root),
                        "label": "generated",
                        "generator": "GPT Image 2.5",
                        "generator_model": "gpt_image_2_5",
                        "provenance": "receipts",
                        "source": "higgsfield:gpt_image_2_5",
                        "license": "自己生成",
                        "id_prefix": "gen",
                        "inventory": str(_inventory(generated_root, root, "gen.jsonl")),
                    },
                ],
                {"minimum_real_groups": 1, "required_generators": {"GPT Image 2.5": 1}},
            )
            rows, build = build_ledger(value, base=root)
            by_label = {row["label"]: row for row in rows}
            self.assertEqual(by_label["real"]["camera"], "Apple iPhone 13")
            self.assertEqual(by_label["generated"]["generator"], "GPT Image 2.5")
            self.assertEqual(by_label["generated"]["generator_model"], "gpt_image_2_5")
            self.assertEqual(by_label["generated"]["provenance"], "receipts/b.json")
            self.assertEqual(by_label["generated"]["format"], "PNG")
            self.assertEqual(build["sources"][1]["skipped"], {"duplicate": 1})
            self.assertEqual(build["sources"][1]["selected_rows"], 1)

    def test_build_ledger_splits_automatic_groups_reproducibly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_root = root / "real"
            real_root.mkdir()
            for index in range(6):
                make_photo(
                    real_root / f"{index}.jpg",
                    model="iPhone 13",
                    size=(8 + index, 8),
                )
            value = manifest(
                [
                    {
                        "root": str(real_root),
                        "label": "real",
                        "source": "所有者による撮影",
                        "license": "評価利用のみ",
                        "id_prefix": "real",
                        "inventory": str(_inventory(real_root, root, "real.jsonl")),
                    }
                ],
                {"minimum_real_groups": 1},
            )
            first, build = build_ledger(
                value, base=root, seed=20260923, evaluation_fraction=0.5
            )
            second, _ = build_ledger(
                value, base=root, seed=20260923, evaluation_fraction=0.5
            )
            self.assertEqual(
                [(row["image_id"], row["split"]) for row in first],
                [(row["image_id"], row["split"]) for row in second],
            )
            self.assertEqual(sum(row["split"] == "evaluation" for row in first), 3)
            self.assertEqual(build["split"]["automatic_rows"], 6)

    def test_coverage_report_flags_gaps_and_held_out_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [
                _row("real-1", "real", "evaluation", camera="Apple iPhone 13"),
                _row("real-2", "real", "evaluation", camera="SONY ILCE-7M3"),
                _row("real-3", "real", "tuning", camera="Apple iPhone 13"),
                _row("gen-1", "generated", "evaluation", generator="GPT Image 2.5"),
                _row("tune-1", "generated", "tuning", generator="GPT Image 2"),
                _row("edit-1", "edited", "evaluation", generator="Nano Banana Pro"),
            ]
            report = coverage_report(
                rows,
                requirements={
                    "minimum_real_groups": 3,
                    "minimum_edited_groups": 1,
                    "required_generators": {"GPT Image 2.5": 2, "Nano Banana Pro": 1},
                    "out_of_scope": ["Midjourney"],
                },
                repository_root=root,
            )
            checks = {check["id"]: check for check in report["checks"]}
            self.assertEqual(checks["real_source_groups"]["status"], "insufficient")
            self.assertEqual(checks["real_source_groups"]["actual"], 2)
            self.assertEqual(checks["generator_groups"]["status"], "insufficient_data")
            self.assertEqual(
                checks["generator_groups"]["details"]["GPT Image 2.5"]["actual"], 1
            )
            self.assertEqual(checks["camera_diversity"]["status"], "met")
            self.assertEqual(checks["heif_inputs"]["status"], "insufficient")
            self.assertEqual(
                checks["split_holdout"]["evaluation_only_versions"],
                ["GPT Image 2.5"],
            )
            self.assertEqual(checks["edited_groups"]["status"], "met")
            self.assertEqual(
                checks["derived_condition_parity"]["status"], "insufficient"
            )
            self.assertEqual(report["out_of_scope_generators"], ["Midjourney"])

    def test_coverage_report_verifies_heif_derived_parity_and_repository_cleanliness(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            heic = root / "photo.heic"
            make_heic_photo(heic)
            rows = [
                {
                    **_row("real-1", "real", "evaluation", camera="Apple iPhone 13"),
                    "path": str(heic),
                    "format": "HEIF",
                },
                _row("real-2", "real", "evaluation", camera="SONY ILCE-7M3"),
                _row("gen-1", "generated", "evaluation", generator="GPT Image 2.5"),
                {
                    **_row("real-1-v1", "real", "evaluation", camera="Apple iPhone 13"),
                    "source_image_id": "real-1",
                    "source_sha256": "a" * 64,
                    "history": [{"operation": "jpeg", "quality": 95}],
                },
                {
                    **_row(
                        "gen-1-v1", "generated", "evaluation", generator="GPT Image 2.5"
                    ),
                    "source_image_id": "gen-1",
                    "source_sha256": "b" * 64,
                    "history": [{"operation": "jpeg", "quality": 95}],
                },
            ]
            report = coverage_report(
                rows,
                requirements={
                    "minimum_real_groups": 1,
                    "required_generators": {"GPT Image 2.5": 1},
                },
                repository_root=root / "repository",
            )
            checks = {check["id"]: check for check in report["checks"]}
            self.assertEqual(checks["heif_inputs"]["status"], "met")
            self.assertEqual(checks["derived_condition_parity"]["status"], "met")
            self.assertEqual(checks["outside_repository"]["status"], "met")
            inside = coverage_report(
                rows,
                requirements={},
                repository_root=Path(rows[0]["path"]).parent,
            )
            checks = {check["id"]: check for check in inside["checks"]}
            self.assertEqual(checks["outside_repository"]["status"], "insufficient")

    def test_derived_parity_ignores_image_specific_output_sizes(self):
        rows = [
            {
                **_row("real-1-v1", "real", "evaluation", camera="Apple iPhone 13"),
                "source_image_id": "real-1",
                "source_sha256": "a" * 64,
                "history": [
                    {"operation": "jpeg", "jpeg_quality": 95, "output_size": [10, 10]}
                ],
            },
            {
                **_row(
                    "gen-1-v1", "generated", "evaluation", generator="GPT Image 2.5"
                ),
                "source_image_id": "gen-1",
                "source_sha256": "b" * 64,
                "history": [
                    {"operation": "jpeg", "jpeg_quality": 95, "output_size": [20, 20]}
                ],
            },
        ]
        report = coverage_report(rows, requirements={"minimum_real_groups": 0})
        checks = {check["id"]: check for check in report["checks"]}
        conditions = checks["derived_condition_parity"]["conditions"]
        self.assertEqual(len(conditions), 1)
        self.assertEqual(
            next(iter(conditions.values())),
            {"real": 1, "generated": 1, "edited": 0},
        )
        self.assertEqual(checks["derived_condition_parity"]["status"], "met")

    def test_build_ledger_rejects_camera_missing_real_by_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_root = root / "real"
            real_root.mkdir()
            make_photo(real_root / "a.jpg", model="")
            value = manifest(
                [
                    {
                        "root": str(real_root),
                        "label": "real",
                        "source": "所有者による撮影",
                        "license": "評価利用のみ",
                        "id_prefix": "real",
                        "inventory": str(_inventory(real_root, root, "real.jsonl")),
                    }
                ],
                {"minimum_real_groups": 1},
            )
            rows, build = build_ledger(value, base=root)
            self.assertEqual(rows, [])
            self.assertEqual(build["sources"][0]["skipped"], {"camera_missing": 1})

    def test_build_ledger_allows_camera_missing_real_when_opted_in(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_root = root / "real"
            real_root.mkdir()
            make_photo(real_root / "a.jpg", model="")
            value = manifest(
                [
                    {
                        "root": str(real_root),
                        "label": "real",
                        "source": "所有者による撮影",
                        "license": "評価利用のみ",
                        "id_prefix": "real",
                        "inventory": str(_inventory(real_root, root, "real.jsonl")),
                    }
                ],
                {"minimum_real_groups": 1},
            )
            rows, build = build_ledger(value, base=root, allow_missing_camera=True)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["camera"], "unknown")
            self.assertEqual(build["sources"][0]["skipped"], {"camera_unknown": 1})

    def test_cli_build_and_report_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = root / "images"
            images.mkdir()
            make_photo(images / "a.jpg", model="iPhone 13")
            make_photo(images / "b.jpg", model="iPhone 13")
            inventory = root / "inventory.jsonl"
            self.assertEqual(main(["scan", str(images), "--output", str(inventory)]), 0)
            self.assertEqual(len(read_inventory(inventory)), 2)
            value = manifest(
                [
                    {
                        "root": str(images),
                        "label": "real",
                        "source": "所有者による撮影",
                        "license": "評価利用のみ",
                        "id_prefix": "real",
                        "inventory": str(inventory),
                        "limit": 1,
                        "split": "evaluation",
                    }
                ],
                {"minimum_real_groups": 1},
            )
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(value), encoding="utf-8")
            ledger = root / "ledger.jsonl"
            report_path = root / "report.json"
            self.assertEqual(
                main(
                    [
                        "build",
                        "--manifest",
                        str(manifest_path),
                        "--ledger",
                        str(ledger),
                        "--report",
                        str(report_path),
                    ]
                ),
                0,
            )
            rows = [json.loads(line) for line in ledger.read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(
                main(
                    [
                        "report",
                        "--ledger",
                        str(ledger),
                        "--manifest",
                        str(manifest_path),
                        "--repository-root",
                        str(root / "elsewhere"),
                        "--report",
                        str(report_path),
                    ]
                ),
                0,
            )
            report = json.loads(report_path.read_text())
            self.assertEqual(report["real_source_groups"], 1)
            self.assertEqual(
                {check["id"]: check["status"] for check in report["checks"]}[
                    "real_source_groups"
                ],
                "met",
            )


def _inventory(root: Path, base: Path, name: str) -> Path:
    rows = scan_directory(root, require_camera=False)
    path = base / name
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _row(image_id: str, label: str, split: str, **fields) -> dict:
    return {
        "image_id": image_id,
        "path": f"/local/{image_id}.png",
        "source_group": image_id,
        "sha256": f"{abs(hash(image_id)) % 10**8:064d}",
        "source": "test",
        "license": "test",
        "label": label,
        "split": split,
        "history": [],
        "format": "PNG",
        **fields,
    }


if __name__ == "__main__":
    unittest.main()
