#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from common import atomic_write_json, read_json, utc_now
from prepare_project import smooth_tracking_segment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="修复指定时间段的四角编号跳变与局部跟踪尖峰")
    parser.add_argument("tracking", type=Path, help="需要修复的 tracking.json")
    parser.add_argument("--start", required=True, type=float, help="处理开始秒数")
    parser.add_argument("--end", required=True, type=float, help="处理结束秒数")
    parser.add_argument("--ramp", type=float, default=0.5, help="两端渐入渐出秒数")
    parser.add_argument("--output", type=Path, help="默认写入 tracking.stabilized.json，不覆盖输入")
    return parser.parse_args()


def motion_stats(frames: list[dict], start: float, end: float) -> dict[str, float | int | None]:
    values: list[float] = []
    max_time: float | None = None
    maximum = -1.0
    for index in range(1, len(frames)):
        current = frames[index]
        time_value = float(current["time"])
        if not start <= time_value <= end:
            continue
        previous = np.array(frames[index - 1]["corners"], dtype=np.float32)
        quad = np.array(current["corners"], dtype=np.float32)
        movement = float(np.mean(np.linalg.norm(quad - previous, axis=1)))
        values.append(movement)
        if movement > maximum:
            maximum, max_time = movement, time_value
    return {
        "samples": len(values),
        "mean_corner_motion": round(float(np.mean(values)), 6) if values else 0.0,
        "max_corner_motion": round(maximum, 6) if values else 0.0,
        "max_motion_time": max_time,
    }


def main() -> int:
    args = parse_args()
    source = args.tracking.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"tracking 不存在: {source}")
    if args.end <= args.start:
        raise ValueError("--end 必须大于 --start")
    data = read_json(source)
    original = data.get("frames") or []
    stabilized = smooth_tracking_segment(original, args.start, args.end, args.ramp)
    data["frames"] = stabilized
    data["stabilization"] = {
        "created_at": utc_now(),
        "method": "cyclic-corner-identity + five-frame median + weighted smoothing",
        "start": args.start,
        "end": args.end,
        "ramp": args.ramp,
        "before": motion_stats(original, args.start, args.end),
        "after": motion_stats(stabilized, args.start, args.end),
    }
    output = args.output.expanduser().resolve() if args.output else source.with_name("tracking.stabilized.json")
    if output == source:
        raise ValueError("默认不覆盖输入；请为 --output 指定另一个路径")
    atomic_write_json(output, data)
    print(json.dumps({"ok": True, "output": str(output), "stabilization": data["stabilization"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
