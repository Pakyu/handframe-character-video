#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from common import atomic_write_json, file_identity, probe_media, require_binary, utc_now


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把原片复制裁剪为视频模型支持的整数秒输入，不覆盖源文件")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--seconds", required=True, type=int, choices=(10, 11))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--preset", default="medium")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"原始视频不存在: {source}")
    if source == output:
        raise ValueError("输出路径不得覆盖原始视频")
    if output.exists():
        raise FileExistsError(f"输出文件已存在: {output}")
    source_meta = probe_media(source)
    if args.start < 0 or args.start + args.seconds > float(source_meta["duration"]) + 0.02:
        raise ValueError("裁剪区间超出原片时长")
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = require_binary("ffmpeg")
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{args.start:.6f}", "-i", str(source), "-t", str(args.seconds),
        "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", args.preset,
        "-crf", str(args.crf), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(output),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        output.unlink(missing_ok=True)
        raise RuntimeError("整数秒裁片失败: " + completed.stderr[-1200:])
    output_meta = probe_media(output)
    if abs(float(output_meta["duration"]) - args.seconds) > 0.08:
        output.unlink(missing_ok=True)
        raise RuntimeError(f"输出时长不是目标整数秒: {output_meta['duration']}")
    evidence = {
        "schema_version": 1,
        "created_at": utc_now(),
        "operation": "non_destructive_integer_duration_trim",
        "source_identity": file_identity(source),
        "source": source_meta,
        "start_seconds": args.start,
        "target_duration_seconds": args.seconds,
        "output_identity": file_identity(output),
        "output": output_meta,
        "source_modified": False,
    }
    evidence_path = output.with_name(output.stem + "-preparation.json")
    atomic_write_json(evidence_path, evidence)
    print(json.dumps({"output": str(output), "evidence": str(evidence_path), "duration": output_meta["duration"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
