# -*- coding: utf-8 -*-

"""ハッシュ固定lockから最小CycloneDX SBOMを生成する。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import __version__  # noqa: E402


_LOCK_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s]+)\s+"
    r"--hash=sha256:(?P<hash>[0-9a-f]{64})$"
)


def read_lock(path: Path) -> list[dict[str, str]]:
    """厳密な1 wheel/1 hash形式を読み、不正行を拒否する。"""

    components: list[dict[str, str]] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"lockの{line_number}行目が不正です")
        item = match.groupdict()
        canonical_name = item["name"].replace("_", "-").casefold()
        if canonical_name in seen:
            raise ValueError(f"lock内でpackageが重複しています: {canonical_name}")
        seen.add(canonical_name)
        components.append(
            {
                "name": canonical_name,
                "version": item["version"],
                "hash": item["hash"],
            }
        )
    if not components:
        raise ValueError("lockにpackageがありません")
    return sorted(components, key=lambda item: item["name"])


def build_sbom(lock_path: Path) -> dict[str, object]:
    lock_bytes = lock_path.read_bytes()
    lock_digest = hashlib.sha256(lock_bytes).hexdigest()
    components = read_lock(lock_path)
    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"ippi-down:{lock_digest}")
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": {
                "type": "application",
                "name": "ippi-down",
                "version": __version__,
            },
            "properties": [
                {
                    "name": "ippi-down:dependency-lock:sha256",
                    "value": lock_digest,
                },
                {
                    "name": "ippi-down:dependency-lock:platform",
                    "value": "CPython 3.11 / Windows x64",
                },
            ],
        },
        "components": [
            {
                "type": "library",
                "name": item["name"],
                "version": item["version"],
                "bom-ref": f"pkg:pypi/{item['name']}@{item['version']}",
                "purl": f"pkg:pypi/{item['name']}@{item['version']}",
                "hashes": [
                    {"alg": "SHA-256", "content": item["hash"]}
                ],
            }
            for item in components
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--lock",
        type=Path,
        default=PROJECT_ROOT / "requirements" / "windows-ci-py311.lock",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = build_sbom(args.lock.resolve(strict=True))
    output = args.output.resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
