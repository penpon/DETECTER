"""Generate AI pictures into ai-picture/ via the higgsfield CLI.

One prompt line per image in a TSV manifest; skips files that already exist.
Usage: uv run python scripts/generate_ai_pictures.py --manifest <tsv> --limit N
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ai-picture"
RECEIPTS = ROOT / "receipts"


def generate(row: dict[str, str], out_dir: Path, receipts: Path) -> int:
    name = row["filename"]
    target = out_dir / name
    if target.exists():
        print(f"skip {name} (exists)", file=sys.stderr)
        return 0
    cmd = [
        "higgsfield",
        "generate",
        "create",
        row["model"],
        "--prompt",
        row["prompt"],
        "--aspect_ratio",
        row.get("aspect_ratio") or "4:3",
        "--wait",
        "--wait-timeout",
        "15m",
        "--json",
    ]
    if row["model"].startswith("gpt_image"):
        cmd += ["--quality", row.get("quality") or "low", "--resolution", "1k"]
    last = None
    for attempt in (1, 2):
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1000, check=False
        )
        try:
            jobs = json.loads(proc.stdout)
            job = jobs[0] if isinstance(jobs, list) else jobs
        except (json.JSONDecodeError, IndexError, KeyError):
            job = None
        if (
            proc.returncode == 0
            and job
            and job.get("status") == "completed"
            and job.get("result_url")
        ):
            url = job["result_url"]
            dl = subprocess.run(
                ["curl", "-sfSL", url, "-o", str(target)], timeout=120, check=False
            )
            if (
                dl.returncode == 0
                and target.exists()
                and target.stat().st_size > 10_000
            ):
                (receipts / f"{target.stem}.json").write_text(
                    json.dumps(job, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
                )
                print(f"ok {name}", file=sys.stderr)
                return 0
            last = f"download failed rc={dl.returncode}"
        else:
            status = job.get("status") if job else proc.stderr.strip()[:200]
            last = f"job failed status={status}"
            if job and job.get("status") in {"completed", "succeeded"}:
                last = "no result_url"
        time.sleep(5 * attempt)
    print(f"FAIL {name}: {last}", file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--receipts", type=Path, default=RECEIPTS)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.receipts.mkdir(parents=True, exist_ok=True)
    rows = [
        r
        for r in csv.DictReader(args.manifest.open(), delimiter="\t")
        if r.get("filename")
    ]
    if args.limit:
        rows = rows[: args.limit]
    failures = 0
    for row in rows:
        failures += generate(row, args.out_dir, args.receipts)
    print(f"done total={len(rows)} failures={failures}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
