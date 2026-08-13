#!/usr/bin/env python3
from __future__ import annotations

SCRIPT_INTERFACE = "internal-module"

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"缺少必需命令: {name}")
    return path


def run_json(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(completed.stdout)


def probe_media(path: Path) -> dict[str, Any]:
    ffprobe = require_binary("ffprobe")
    data = run_json(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    if video is None:
        raise RuntimeError(f"没有视频流: {path}")
    duration = float(fmt.get("duration") or video.get("duration") or 0)
    if duration <= 0:
        raise RuntimeError(f"无法读取有效时长: {path}")
    fps_text = str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1")
    try:
        num, den = fps_text.split("/", 1)
        fps = float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "duration": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": fps,
        "video_codec": video.get("codec_name"),
        "pixel_format": video.get("pix_fmt"),
        "has_audio": audio is not None,
        "audio_codec": audio.get("codec_name") if audio else None,
    }


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def json_sha256(data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    stat = resolved.stat()
    return {"path": str(resolved), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def default_quad() -> list[list[float]]:
    return [[0.22, 0.23], [0.78, 0.20], [0.82, 0.72], [0.18, 0.76]]


def validate_corners(corners: Any) -> list[list[float]]:
    if not isinstance(corners, list) or len(corners) != 4:
        raise ValueError("corners 必须包含四个点")
    out: list[list[float]] = []
    for point in corners:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError("每个 corner 必须是 [x, y]")
        x, y = float(point[0]), float(point[1])
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError("corner 坐标必须在 0..1")
        out.append([x, y])
    hull = sorted((point[0], point[1]) for point in out)
    def cross(origin: tuple[float, float], first: tuple[float, float], second: tuple[float, float]) -> float:
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (first[1] - origin[1]) * (second[0] - origin[0])
    lower: list[tuple[float, float]] = []
    upper: list[tuple[float, float]] = []
    for point in hull:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(hull):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    convex = lower[:-1] + upper[:-1]
    area = 0.0
    for index, point in enumerate(convex):
        other = convex[(index + 1) % len(convex)]
        area += point[0] * other[1] - other[0] * point[1]
    if len(convex) < 3 or abs(area) / 2 < 0.001:
        raise ValueError("四个角点的覆盖面积过小")
    return out


def segments_intersect(a: Any, b: Any, c: Any, d: Any, epsilon: float = 1e-9) -> bool:
    """Return True when two non-adjacent 2D segments cross or touch."""
    def orientation(p: Any, q: Any, r: Any) -> float:
        return (float(q[0]) - float(p[0])) * (float(r[1]) - float(p[1])) - (float(q[1]) - float(p[1])) * (float(r[0]) - float(p[0]))

    def on_segment(p: Any, q: Any, r: Any) -> bool:
        return (
            min(float(p[0]), float(r[0])) - epsilon <= float(q[0]) <= max(float(p[0]), float(r[0])) + epsilon
            and min(float(p[1]), float(r[1])) - epsilon <= float(q[1]) <= max(float(p[1]), float(r[1])) + epsilon
        )

    o1, o2 = orientation(a, b, c), orientation(a, b, d)
    o3, o4 = orientation(c, d, a), orientation(c, d, b)
    if ((o1 > epsilon and o2 < -epsilon) or (o1 < -epsilon and o2 > epsilon)) and ((o3 > epsilon and o4 < -epsilon) or (o3 < -epsilon and o4 > epsilon)):
        return True
    return (
        (abs(o1) <= epsilon and on_segment(a, c, b))
        or (abs(o2) <= epsilon and on_segment(a, d, b))
        or (abs(o3) <= epsilon and on_segment(c, a, d))
        or (abs(o4) <= epsilon and on_segment(c, b, d))
    )


def corners_self_intersect(corners: Any) -> bool:
    """Detect a bow-tie path while preserving semantic fingertip order."""
    if corners is None or len(corners) != 4:
        return False
    return segments_intersect(corners[0], corners[1], corners[2], corners[3]) or segments_intersect(corners[1], corners[2], corners[3], corners[0])


def default_review_config(
    duration: float,
    bgm_available: bool,
    transform_required: bool = False,
    inside_count: int = 1,
    sequence_start_seconds: float = 0.0,
) -> dict[str, Any]:
    inside_count = max(1, int(inside_count))
    sequence_start_seconds = clamp(float(sequence_start_seconds), 0.0, max(0.0, duration))
    sequence_span = max(0.25, duration - sequence_start_seconds)
    return {
        "schema_version": SCHEMA_VERSION,
        "fit_mode": "clip",
        "keyframes": [],
        "invert": {"enabled": False, "start": 0.0, "end": duration},
        "audio": {
            "mode": "original",
            "bgm_volume": 0.35,
            "available": bgm_available,
        },
        "inside_loop": False,
        "transform_review": {"required": transform_required, "approved": False},
        "transform_reviews": [
            {"index": index, "approved": False} for index in range(inside_count)
        ] if transform_required else [],
        "style_sequence": {
            "enabled": inside_count > 1,
            "start_seconds": sequence_start_seconds,
            "segment_seconds": max(0.25, sequence_span / inside_count),
            "transition_seconds": 0.12,
            "order": list(range(inside_count)),
            "global_timeline": True,
            "loop_order": False,
        },
        "review_notes": "",
    }


def validate_review_config(config: Any, duration: float, bgm_available: bool, transform_required: bool = False, inside_count: int = 1) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("审核配置必须是对象")
    requested_fit_mode = str(config.get("fit_mode", "clip"))
    if requested_fit_mode not in {"perspective", "clip"}:
        raise ValueError("fit_mode 只能是 clip；旧版 perspective 会自动迁移")
    fit_mode = "clip"
    keyframes = []
    for item in config.get("keyframes", []):
        time_value = clamp(float(item.get("time", 0)), 0, duration)
        keyframes.append({"time": time_value, "corners": validate_corners(item.get("corners"))})
    keyframes.sort(key=lambda item: item["time"])
    invert_raw = config.get("invert") or {}
    invert_start = clamp(float(invert_raw.get("start", 0)), 0, duration)
    invert_end = clamp(float(invert_raw.get("end", duration)), 0, duration)
    if invert_end < invert_start:
        invert_start, invert_end = invert_end, invert_start
    audio_raw = config.get("audio") or {}
    transform_raw = config.get("transform_review") or {}
    inside_count = max(1, int(inside_count))
    raw_reviews = config.get("transform_reviews") or []
    review_approvals = {
        int(item.get("index", -1)): bool(item.get("approved", False))
        for item in raw_reviews if isinstance(item, dict)
    }
    if transform_required and inside_count == 1 and 0 not in review_approvals:
        review_approvals[0] = bool(transform_raw.get("approved", False))
    transform_reviews = [
        {"index": index, "approved": bool(review_approvals.get(index, False))}
        for index in range(inside_count)
    ] if transform_required else []
    sequence_raw = config.get("style_sequence") or {}
    order = sequence_raw.get("order", list(range(inside_count)))
    if not isinstance(order, list) or not order:
        raise ValueError("style_sequence.order 必须是非空数组")
    order = [int(index) for index in order]
    if any(index < 0 or index >= inside_count for index in order):
        raise ValueError("style_sequence.order 含不存在的转绘视频")
    if bool(sequence_raw.get("enabled", inside_count > 1)) and sorted(order) != list(range(inside_count)):
        raise ValueError("启用多角色轮换时，style_sequence.order 必须且只能包含每条转绘视频一次")
    start_seconds = clamp(float(sequence_raw.get("start_seconds", 0.0)), 0.0, max(0.0, duration))
    segment_seconds = clamp(float(sequence_raw.get("segment_seconds", max(0.25, (duration - start_seconds) / inside_count))), 0.25, max(0.25, duration))
    transition_seconds = clamp(float(sequence_raw.get("transition_seconds", 0.12)), 0.0, min(0.5, segment_seconds / 2))
    audio_mode = str(audio_raw.get("mode", "original"))
    if audio_mode not in {"original", "replace", "mix", "none"}:
        raise ValueError("audio.mode 不合法")
    if audio_mode in {"replace", "mix"} and not bgm_available:
        raise ValueError("没有提供 BGM，不能选择替换或混合音频")
    return {
        "schema_version": SCHEMA_VERSION,
        "fit_mode": fit_mode,
        "keyframes": keyframes,
        "invert": {"enabled": bool(invert_raw.get("enabled", False)), "start": invert_start, "end": invert_end},
        "audio": {
            "mode": audio_mode,
            "bgm_volume": clamp(float(audio_raw.get("bgm_volume", 0.35)), 0.0, 1.0),
            "available": bgm_available,
        },
        "inside_loop": False,
        "transform_review": {
            "required": bool(transform_required),
            "approved": all(item["approved"] for item in transform_reviews) if transform_required else False,
        },
        "transform_reviews": transform_reviews,
        "style_sequence": {
            "enabled": bool(sequence_raw.get("enabled", inside_count > 1)) and inside_count > 1,
            "start_seconds": start_seconds,
            "segment_seconds": segment_seconds,
            "transition_seconds": transition_seconds,
            "order": order,
            "global_timeline": True,
            "loop_order": bool(sequence_raw.get("loop_order", False)),
        },
        "review_notes": str(config.get("review_notes", ""))[:2000],
    }
