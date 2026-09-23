"""Build a local evaluation cohort ledger and report its coverage."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .core import ensure_heif_opener, inspect_image
from .ledger import split_ledger
from .pipeline import _generator_coverage

IMAGE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".heif",
    ".webp",
    ".tif",
    ".tiff",
}
SKIP_DIRECTORIES = {"@Recently-Snapshot", "@Recycle", "@eaDir", ".thumbnails"}
HEIF_FORMATS = {"HEIF", "HEIC", "AVIF"}
REQUIRED_SOURCE_FIELDS = ("root", "label", "source", "license", "id_prefix")


def _inspect_candidate(path: Path, require_camera: bool) -> dict[str, Any] | None:
    try:
        media = inspect_image(path)
        make, model = _camera_of(path)
    except (OSError, ValueError):
        return None
    if require_camera and not model:
        return None
    return {
        "path": str(path),
        "sha256": media["sha256"],
        "format": media["format"],
        "width": media["width"],
        "height": media["height"],
        "make": make,
        "model": model,
    }


def scan_directory(
    root: Path | str,
    *,
    limit: int | None = None,
    threads: int = 8,
    suffixes: Collection[str] | None = None,
    require_camera: bool = True,
    progress: Any = None,
) -> list[dict[str, Any]]:
    """Verify local images and record identity, format, and camera metadata.

    Files are inspected in parallel because a network mount is dominated by
    per-file latency rather than bandwidth.
    """
    if threads < 1:
        raise ValueError("threads は1以上が必要です")
    if limit is not None and limit < 1:
        raise ValueError("limit は1以上が必要です")
    wanted = {
        suffix if suffix.startswith(".") else f".{suffix}"
        for suffix in (IMAGE_SUFFIXES if suffixes is None else suffixes)
    }
    wanted = {suffix.lower() for suffix in wanted}
    ensure_heif_opener()
    directory_root = Path(root).expanduser().resolve()
    paths = []
    for directory, dirnames, filenames in os.walk(directory_root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRECTORIES]
        paths.extend(
            Path(directory) / name
            for name in sorted(filenames, key=str.lower)
            if Path(name).suffix.lower() in wanted
        )
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=threads) as pool:
        for row in pool.map(
            lambda path: _inspect_candidate(path, require_camera), paths
        ):
            if row is None:
                continue
            rows.append(row)
            if progress is not None and len(rows) % 250 == 0:
                progress(f"kept={len(rows)}")
            if limit is not None and len(rows) >= limit:
                pool.shutdown(wait=False, cancel_futures=True)
                break
    return rows


def _camera_of(path: Path) -> tuple[str, str]:
    from PIL import Image

    with Image.open(path) as image:
        exif = image.getexif()
        make = str(exif.get(271) or "").strip()
        model = str(exif.get(272) or "").strip()
    return make, model


def read_inventory(path: Path | str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _source_rows(
    entry: dict[str, Any],
    inventory: list[dict[str, Any]],
    *,
    seen_hashes: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    label = entry["label"]
    if label not in {"real", "generated", "edited"}:
        raise ValueError(f"未対応のラベルです: {label}")
    generator = entry.get("generator")
    if label != "real" and not isinstance(generator, str):
        raise ValueError(f"{label} には generator が必要です")
    history = entry.get("history", [])
    if not isinstance(history, list):
        raise TypeError("history は配列が必要です")
    if label == "edited" and not history:
        raise ValueError("edited には加工履歴が必要です")
    rows: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    for index, item in enumerate(inventory, 1):
        if item["sha256"] in seen_hashes:
            reasons["duplicate"] += 1
            continue
        seen_hashes.add(item["sha256"])
        row: dict[str, Any] = {
            "image_id": f"{entry['id_prefix']}-{index:04d}",
            "path": item["path"],
            "source_group": f"{entry['id_prefix']}-{index:04d}",
            "sha256": item["sha256"],
            "source": entry["source"],
            "license": entry["license"],
            "label": label,
            "split": entry.get("split") or "unassigned",
            "history": history,
            "format": item["format"],
        }
        if label == "real":
            camera = " ".join(value for value in (item["make"], item["model"]) if value)
            if not camera:
                reasons["camera_missing"] += 1
                continue
            row["camera"] = camera
        else:
            row["generator"] = generator
            if entry.get("generator_model"):
                row["generator_model"] = entry["generator_model"]
            if entry.get("provenance"):
                row["provenance"] = f"{entry['provenance']}/{_stem(item['path'])}.json"
        rows.append(row)
        if entry.get("limit") and len(rows) >= int(entry["limit"]):
            break
    return rows, dict(reasons)


def _stem(path: str) -> str:
    return Path(path).stem


def build_ledger(
    manifest: dict[str, Any],
    *,
    base: Path,
    seed: int | None = None,
    evaluation_fraction: float = 0.2,
) -> tuple[list[dict], dict]:
    """Turn inventoried local images into ledger rows plus a build report."""
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("manifest には sources が必要です")
    seen_hashes: set[str] = set()
    rows: list[dict[str, Any]] = []
    report: dict[str, Any] = {"sources": []}
    for entry in sources:
        for field in REQUIRED_SOURCE_FIELDS:
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"source entry には {field} が必要です")
        inventory_path = Path(entry.get("inventory") or entry["root"])
        if not inventory_path.is_absolute():
            inventory_path = base / inventory_path
        inventory = read_inventory(inventory_path)
        selected, reasons = _source_rows(entry, inventory, seen_hashes=seen_hashes)
        rows.extend(selected)
        report["sources"].append(
            {
                "id_prefix": entry["id_prefix"],
                "label": entry["label"],
                "inventory": str(inventory_path),
                "inventory_rows": len(inventory),
                "selected_rows": len(selected),
                "skipped": reasons,
            }
        )
    if seed is not None:
        automatic = [row for row in rows if row["split"] == "unassigned"]
        fixed = [row for row in rows if row["split"] != "unassigned"]
        if automatic:
            automatic = split_ledger(
                automatic, seed=seed, evaluation_fraction=evaluation_fraction
            )
        rows = sorted([*fixed, *automatic], key=lambda row: row["image_id"])
        report["split"] = {
            "seed": seed,
            "evaluation_fraction": evaluation_fraction,
            "automatic_rows": len(automatic),
            "fixed_rows": len(fixed),
        }
    return rows, report


def _split_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_label: dict[str, Counter[str]] = {}
    for row in rows:
        by_label.setdefault(row["label"], Counter())[row["split"]] += 1
    return {label: dict(sorted(counts.items())) for label, counts in by_label.items()}


def _derived_parity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    conditions: dict[str, dict[str, int]] = {}
    for row in rows:
        if not row.get("source_image_id") or not row["history"]:
            continue
        # The requested condition is comparable across images; the resulting
        # output size is image specific and must not split the comparison.
        condition = {
            name: value
            for name, value in row["history"][-1].items()
            if name != "output_size"
        }
        key = json.dumps(condition, ensure_ascii=False, sort_keys=True)
        bucket = conditions.setdefault(key, {"real": 0, "generated": 0, "edited": 0})
        bucket[row["label"]] += 1
    return {
        "conditions": dict(sorted(conditions.items())),
        "status": "not_provided" if not conditions else "reported",
    }


def coverage_report(
    rows: list[dict[str, Any]],
    *,
    requirements: dict[str, Any],
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Summarise how far the local cohort satisfies the issue requirements."""
    minimum_real = int(requirements.get("minimum_real_groups", 3000))
    minimum_edited = int(requirements.get("minimum_edited_groups", 1))
    required_generators = {
        str(name): int(count)
        for name, count in (requirements.get("required_generators") or {}).items()
    }
    evaluation = [row for row in rows if row["split"] == "evaluation"]
    real_groups = {row["source_group"] for row in evaluation if row["label"] == "real"}
    edited_groups = {
        row["source_group"] for row in evaluation if row["label"] == "edited"
    }
    cameras = Counter(
        row["camera"] for row in rows if row["label"] == "real" and row.get("camera")
    )
    formats = Counter(row["format"] for row in rows)
    heic_rows = [row for row in rows if row["format"] in HEIF_FORMATS]
    generator_coverage = _generator_coverage(
        rows, split="evaluation", required=required_generators
    )
    tuning_generators = {
        str(row.get("generator"))
        for row in rows
        if row["split"] == "tuning" and row["label"] == "generated"
    }
    evaluation_generators = {
        str(row.get("generator"))
        for row in rows
        if row["split"] == "evaluation" and row["label"] == "generated"
    }
    held_out = sorted(evaluation_generators - tuning_generators)
    parity = _derived_parity(rows)
    checks = [
        {
            "id": "real_source_groups",
            "status": "met" if len(real_groups) >= minimum_real else "insufficient",
            "required": minimum_real,
            "actual": len(real_groups),
        },
        {
            "id": "generator_groups",
            "status": generator_coverage["status"],
            "details": generator_coverage["details"],
        },
        {
            "id": "camera_diversity",
            "status": "met" if len(cameras) >= 2 else "insufficient",
            "cameras": len(cameras),
        },
        {
            "id": "heif_inputs",
            "status": "met" if heic_rows else "insufficient",
            "images": len(heic_rows),
        },
        {
            "id": "split_holdout",
            "status": "met" if held_out else "insufficient",
            "evaluation_only_versions": held_out,
        },
        {
            "id": "derived_condition_parity",
            "status": "met"
            if parity["conditions"]
            and all(
                counts["real"] and counts["generated"]
                for counts in parity["conditions"].values()
            )
            else "insufficient",
            "conditions": parity["conditions"],
        },
        {
            "id": "edited_groups",
            "status": "met" if len(edited_groups) >= minimum_edited else "insufficient",
            "required": minimum_edited,
            "actual": len(edited_groups),
        },
    ]
    if repository_root is not None:
        offenders = _local_paths(rows, repository_root)
        checks.append(
            {
                "id": "outside_repository",
                "status": "met" if not offenders else "insufficient",
                "images_inside_repository": offenders[:10],
            }
        )
    return {
        "schema_version": 1,
        "images": len(rows),
        "source_groups": len({row["source_group"] for row in rows}),
        "by_label_and_split": _split_summary(rows),
        "real_source_groups": len(real_groups),
        "generator_coverage": generator_coverage,
        "cameras": dict(sorted(cameras.items())),
        "formats": dict(sorted(formats.items())),
        "evaluation_only_generator_versions": held_out,
        "out_of_scope_generators": list(requirements.get("out_of_scope") or []),
        "checks": checks,
    }


def _local_paths(rows: list[dict[str, Any]], repository_root: Path) -> list[str]:
    root = repository_root.expanduser().resolve()
    offenders = []
    for row in rows:
        path = Path(row["path"]).expanduser()
        if not path.is_absolute():
            offenders.append(row["image_id"])
            continue
        if root in path.resolve().parents or path.resolve() == root:
            offenders.append(row["image_id"])
    return offenders


def _write(path: Path | str, payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if str(path) == "-":
        print(text, end="")
        return
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ローカル画像から評価コホートの台帳と充足状況を作ります"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan")
    scan.add_argument("root", type=Path)
    scan.add_argument("--output", type=Path, required=True)
    scan.add_argument("--limit", type=int)
    scan.add_argument("--threads", type=int, default=8)
    scan.add_argument(
        "--suffixes",
        help="読み込む拡張子をカンマ区切りで指定します（既定は画像全般）",
    )
    scan.add_argument("--allow-missing-camera", action="store_true")
    build = commands.add_parser("build")
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--ledger", type=Path, required=True)
    build.add_argument("--seed", type=int)
    build.add_argument("--evaluation-fraction", type=float, default=0.2)
    build.add_argument("--report", type=Path, default=Path("-"))
    report = commands.add_parser("report")
    report.add_argument("--ledger", type=Path, required=True)
    report.add_argument("--manifest", type=Path, required=True)
    report.add_argument("--repository-root", type=Path, default=Path.cwd())
    report.add_argument(
        "--verify-files",
        action="store_true",
        help="台帳の全画像を読み直してSHA-256を確認します（時間がかかります）",
    )
    report.add_argument("--report", type=Path, default=Path("-"))
    args = parser.parse_args(argv)
    from .ledger import read_ledger

    try:
        if args.command == "scan":
            rows = scan_directory(
                args.root,
                limit=args.limit,
                threads=args.threads,
                suffixes=args.suffixes.split(",") if args.suffixes else None,
                require_camera=not args.allow_missing_camera,
                progress=lambda message: print(message, file=sys.stderr),
            )
            text = "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows
            )
            if str(args.output) == "-":
                print(text, end="")
            else:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text, encoding="utf-8")
            print(f"images={len(rows)}", file=sys.stderr)
            return 0
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if args.command == "build":
            rows, build_report = build_ledger(
                manifest,
                base=args.manifest.parent,
                seed=args.seed,
                evaluation_fraction=args.evaluation_fraction,
            )
            text = "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows
            )
            if str(args.ledger) == "-":
                print(text, end="")
            else:
                args.ledger.parent.mkdir(parents=True, exist_ok=True)
                args.ledger.write_text(text, encoding="utf-8")
            _write(
                args.report,
                {
                    "schema_version": 1,
                    "build": build_report,
                    "coverage": coverage_report(
                        rows,
                        requirements=manifest.get("requirements", {}),
                        repository_root=Path.cwd(),
                    ),
                },
            )
            return 0
        rows = read_ledger(args.ledger, verify_files=args.verify_files)
        coverage = coverage_report(
            rows,
            requirements=manifest.get("requirements", {}),
            repository_root=args.repository_root,
        )
        coverage["integrity_verified"] = bool(args.verify_files)
        _write(args.report, coverage)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"コホート処理に失敗しました: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
