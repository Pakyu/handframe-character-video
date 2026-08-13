#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from common import file_identity, json_sha256, read_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="等待用户在审核页确认配置")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--timeout", type=float, default=3600)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project = args.project_dir.expanduser().resolve()
    manifest = read_json(project / "manifest.json")
    deadline = time.monotonic() + args.timeout
    confirmation_path = project / "review_confirmed.json"
    while time.monotonic() < deadline:
        if confirmation_path.is_file():
            confirmation = read_json(confirmation_path)
            config = read_json(project / "review_config.json")
            if confirmation.get("config_sha256") != json_sha256(config):
                raise RuntimeError("审核配置在确认后发生变化，必须重新确认")
            for key in ("source", "inside"):
                current = file_identity(Path(manifest[key]["path"]))
                recorded = confirmation.get(key)
                if not recorded or current["size_bytes"] != recorded.get("size_bytes") or current["mtime_ns"] != recorded.get("mtime_ns"):
                    raise RuntimeError(f"{key} 文件在审核后发生变化")
            print(json.dumps({"ok": True, "project_dir": str(project), "confirmation": confirmation}, ensure_ascii=False, indent=2))
            return 0
        time.sleep(0.5)
    raise TimeoutError(f"等待审核确认超时: {confirmation_path}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
