"""Check tracked artifacts and exercise the CLI with a temporary synthetic image."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode()
    forbidden = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".pem",
        ".key",
        ".pt",
        ".pth",
        ".safetensors",
    }
    for name in tracked.split("\0"):
        if not name:
            continue
        path = root / name
        assert path.suffix.lower() not in forbidden, f"非公開の入力・モデル候補: {name}"
        assert path.parts[len(root.parts)] not in {
            "data",
            "results",
            ".cache",
            ".venv",
        }, name
        assert not path.name.startswith(".env"), name
        assert path.stat().st_size < 5 * 1024 * 1024, f"5MiB以上の追跡ファイル: {name}"
        private_key_header = (
            rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE" + rb" KEY-----"
        )
        assert not re.search(private_key_header, path.read_bytes()), name
    with tempfile.TemporaryDirectory(prefix="detecter-smoke-") as temporary:
        image = Path(temporary) / "synthetic.png"
        Image.new("RGB", (32, 24), "white").save(image)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "detecter.cli",
                "analyze-legacy",
                str(image),
                "--skip-ufd",
                "--output",
                "-",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        record = json.loads(result.stdout)
        assert record["media"]["format"] == "PNG"
        assert record["c2pa"]["status"] == "absent"
        assert record["universal_fake_detect"]["status"] == "skipped"
    print("追跡ファイル検査と非機密画像のCLI確認に成功しました。")


if __name__ == "__main__":
    main()
