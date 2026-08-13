#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from common import (
    atomic_write_json,
    corners_self_intersect,
    file_identity,
    json_sha256,
    probe_media,
    read_json,
    require_binary,
    utc_now,
    validate_review_config,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="根据已确认配置渲染手势框视频")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--output", type=Path, help="默认写入项目目录 output.mp4")
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--preset", default="medium")
    return parser.parse_args()


def interpolate_frames(frames: list[dict[str, Any]], time_value: float) -> np.ndarray:
    if not frames:
        raise RuntimeError("没有可用轨迹帧")
    if time_value <= float(frames[0]["time"]):
        return np.array(frames[0]["corners"], dtype=np.float32)
    if time_value >= float(frames[-1]["time"]):
        return np.array(frames[-1]["corners"], dtype=np.float32)
    low, high = 0, len(frames) - 1
    while high - low > 1:
        middle = (low + high) // 2
        if float(frames[middle]["time"]) <= time_value:
            low = middle
        else:
            high = middle
    first, second = frames[low], frames[high]
    denominator = max(1e-6, float(second["time"]) - float(first["time"]))
    factor = (time_value - float(first["time"])) / denominator
    a = np.array(first["corners"], dtype=np.float32)
    b = np.array(second["corners"], dtype=np.float32)
    return a * (1 - factor) + b * factor


def frame_window_open(frame: dict[str, Any]) -> bool:
    if "visible" in frame:
        return bool(frame["visible"])
    return str(frame.get("source", "default")) in {"detected", "held"}


def window_open_at(frames: list[dict[str, Any]], time_value: float) -> bool:
    if not frames:
        return False
    if time_value <= float(frames[0]["time"]):
        return frame_window_open(frames[0])
    low, high = 0, len(frames) - 1
    while high - low > 1:
        middle = (low + high) // 2
        if float(frames[middle]["time"]) <= time_value:
            low = middle
        else:
            high = middle
    if time_value >= float(frames[-1]["time"]):
        low = len(frames) - 1
    return frame_window_open(frames[low])


def style_selection_at(sequence: dict[str, Any], time_value: float, inside_count: int) -> tuple[int, int | None, float]:
    """Return current index, optional next index and crossfade weight on the global timeline."""
    if inside_count <= 1 or not sequence.get("enabled", False):
        return 0, None, 0.0
    order = [int(index) for index in sequence.get("order", list(range(inside_count)))]
    segment = max(0.25, float(sequence.get("segment_seconds", 1.5)))
    transition = max(0.0, min(float(sequence.get("transition_seconds", 0.12)), segment / 2))
    start = max(0.0, float(sequence.get("start_seconds", 0.0)))
    sequence_time = max(0.0, time_value - start)
    slot = int(sequence_time // segment)
    local = sequence_time - slot * segment
    loop_order = bool(sequence.get("loop_order", False))
    position = slot % len(order) if loop_order else min(slot, len(order) - 1)
    current = order[position]
    if transition <= 0 or local < segment - transition:
        return current, None, 0.0
    if not loop_order and position >= len(order) - 1:
        return current, None, 0.0
    next_index = order[(position + 1) % len(order)]
    weight = min(1.0, max(0.0, (local - (segment - transition)) / transition))
    return current, next_index, weight


def select_style_frame(readers: list["FrameReader"], sequence: dict[str, Any], time_value: float) -> tuple[np.ndarray, int, int | None, float]:
    current, next_index, weight = style_selection_at(sequence, time_value, len(readers))
    frame = readers[current].at(time_value)
    if next_index is not None and weight > 0:
        next_frame = readers[next_index].at(time_value)
        if next_frame.shape[:2] != frame.shape[:2]:
            next_frame = resized(next_frame, frame.shape[1], frame.shape[0])
        frame = cv2.addWeighted(frame, 1 - weight, next_frame, weight, 0)
    return frame, current, next_index, weight


class FrameReader:
    def __init__(self, path: Path, loop: bool):
        self.capture = cv2.VideoCapture(str(path))
        if not self.capture.isOpened():
            raise RuntimeError(f"无法打开框内视频: {path}")
        self.fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 25.0)
        self.count = max(1, int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT) or 1))
        self.duration = self.count / self.fps
        self.loop = loop
        self.cached_index = -1
        self.cached_frame: np.ndarray | None = None

    def at(self, time_value: float) -> np.ndarray:
        if self.loop:
            time_value %= max(self.duration, 1 / self.fps)
        else:
            time_value = min(time_value, max(0.0, self.duration - 1 / self.fps))
        target = max(0, min(self.count - 1, int(round(time_value * self.fps))))
        if target == self.cached_index and self.cached_frame is not None:
            return self.cached_frame.copy()
        if target != self.cached_index + 1:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, frame = self.capture.read()
        if not ok:
            if self.cached_frame is None:
                raise RuntimeError(f"无法读取框内视频帧: {target}")
            return self.cached_frame.copy()
        self.cached_index = target
        self.cached_frame = frame
        return frame.copy()

    def close(self) -> None:
        self.capture.release()


def resized(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)


def compose(base: np.ndarray, overlay: np.ndarray, corners: np.ndarray, mode: str, window_open: bool = True) -> np.ndarray:
    if mode != "clip":
        raise ValueError("只支持全画面对齐的动态遮罩窗口；禁止透视拉伸框内视频")
    if not window_open:
        return base.copy()
    height, width = base.shape[:2]
    points = np.column_stack((corners[:, 0] * width, corners[:, 1] * height)).astype(np.float32)
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(mask, [points.astype(np.int32)], 255)
    aligned_overlay = resized(overlay, width, height)
    inverse = cv2.bitwise_not(mask)
    return cv2.add(cv2.bitwise_and(base, base, mask=inverse), cv2.bitwise_and(aligned_overlay, aligned_overlay, mask=mask))


def build_ffmpeg_command(
    ffmpeg: str,
    silent_video: Path,
    source: Path,
    bgm: Path | None,
    output: Path,
    audio_mode: str,
    bgm_volume: float,
    source_has_audio: bool,
    crf: int,
    preset: str,
) -> tuple[list[str], str]:
    common_video = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if audio_mode == "original" and source_has_audio:
        return ([ffmpeg, "-y", "-i", str(silent_video), "-i", str(source), "-map", "0:v:0", "-map", "1:a:0?", *common_video, "-c:a", "aac", "-b:a", "192k", "-shortest", str(output)], "original")
    if audio_mode == "mix" and source_has_audio and bgm:
        mix_filter = f"[1:a]volume=1[a0];[2:a]volume={bgm_volume:.3f}[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a]"
        return ([ffmpeg, "-y", "-i", str(silent_video), "-i", str(source), "-stream_loop", "-1", "-i", str(bgm), "-filter_complex", mix_filter, "-map", "0:v:0", "-map", "[a]", *common_video, "-c:a", "aac", "-b:a", "192k", "-shortest", str(output)], "mix")
    if audio_mode in {"replace", "mix"} and bgm:
        return ([ffmpeg, "-y", "-i", str(silent_video), "-stream_loop", "-1", "-i", str(bgm), "-map", "0:v:0", "-map", "1:a:0", *common_video, "-af", f"volume={bgm_volume:.3f}", "-c:a", "aac", "-b:a", "192k", "-shortest", str(output)], "replace")
    return ([ffmpeg, "-y", "-i", str(silent_video), "-map", "0:v:0", *common_video, "-an", str(output)], "none")


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    project = args.project_dir.expanduser().resolve()
    manifest = read_json(project / "manifest.json")
    tracking = read_json(project / "tracking.json")
    raw_config = read_json(project / "review_config.json")
    confirmation = read_json(project / "review_confirmed.json")
    source = Path(manifest["source"]["path"])
    inside_metas = manifest.get("insides") or [manifest["inside"]]
    inside_paths = [Path(item["path"]) for item in inside_metas]
    bgm = Path(manifest["bgm"]["path"]) if manifest.get("bgm") else None
    origins = manifest.get("inside_origins") or [manifest.get("inside_origin", {})]
    transform_required = any(origin.get("route") == "ai-video-edit" for origin in origins)
    config = validate_review_config(raw_config, float(manifest["source"]["duration"]), bgm is not None, transform_required, len(inside_paths))
    if transform_required and not config.get("transform_review", {}).get("approved"):
        raise RuntimeError("AI 转绘视频尚未通过人工审核")
    if confirmation.get("config_sha256") != json_sha256(config):
        raise RuntimeError("审核配置摘要与确认记录不一致，必须重新确认")
    for key, path in (("source", source), ("bgm", bgm)):
        if path is None:
            continue
        current = file_identity(path)
        recorded = confirmation.get(key)
        if not recorded or current["size_bytes"] != recorded.get("size_bytes") or current["mtime_ns"] != recorded.get("mtime_ns"):
            raise RuntimeError(f"{key} 文件在确认后发生变化")
    recorded_insides = confirmation.get("insides") or ([confirmation.get("inside")] if confirmation.get("inside") else [])
    if len(recorded_insides) != len(inside_paths):
        raise RuntimeError("审核确认中的转绘视频数量不一致")
    for index, path in enumerate(inside_paths):
        current, recorded = file_identity(path), recorded_insides[index]
        if current["size_bytes"] != recorded.get("size_bytes") or current["mtime_ns"] != recorded.get("mtime_ns"):
            raise RuntimeError(f"inside {index + 1} 文件在确认后发生变化")

    source_capture = cv2.VideoCapture(str(source))
    if not source_capture.isOpened():
        raise RuntimeError(f"无法打开原始视频: {source}")
    width = int(source_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(source_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(source_capture.get(cv2.CAP_PROP_FPS) or manifest["source"].get("fps") or 25.0)
    total_frames = int(source_capture.get(cv2.CAP_PROP_FRAME_COUNT) or round(float(manifest["source"]["duration"]) * fps))
    if width <= 0 or height <= 0 or fps <= 0:
        raise RuntimeError("原始视频参数无效")
    inside_readers = [FrameReader(path, False) for path in inside_paths]
    silent_video = project / "_render_video_only.mp4"
    writer = cv2.VideoWriter(str(silent_video), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("无法创建临时视频编码器")
    track_frames = config["keyframes"] if config["keyframes"] else tracking["frames"]
    rendered = 0
    window_open_frames = 0
    first_window_open_time: float | None = None
    style_frame_counts = [0 for _ in inside_readers]
    transition_frame_count = 0
    crossing_frame_times: list[float] = []
    try:
        while True:
            ok, source_frame = source_capture.read()
            if not ok:
                break
            time_value = rendered / fps
            inside_frame, style_index, next_style_index, transition_weight = select_style_frame(inside_readers, config["style_sequence"], time_value)
            style_frame_counts[style_index] += 1
            if next_style_index is not None and transition_weight > 0:
                transition_frame_count += 1
            corners = interpolate_frames(track_frames, time_value)
            if corners_self_intersect(corners):
                crossing_frame_times.append(round(time_value, 4))
            window_open = window_open_at(tracking["frames"], time_value)
            if window_open:
                window_open_frames += 1
                if first_window_open_time is None:
                    first_window_open_time = time_value
            inverted = bool(window_open and config["invert"]["enabled"] and config["invert"]["start"] <= time_value <= config["invert"]["end"])
            if inverted:
                base = resized(inside_frame, width, height)
                overlay = source_frame
            else:
                base = source_frame
                overlay = inside_frame
            frame = compose(base, overlay, corners, config["fit_mode"], window_open=window_open)
            writer.write(frame)
            rendered += 1
    finally:
        writer.release()
        source_capture.release()
        for reader in inside_readers:
            reader.close()
    if rendered == 0 or not silent_video.is_file() or silent_video.stat().st_size < 1024:
        raise RuntimeError("没有生成有效临时视频")

    output = (args.output or (project / "output.mp4")).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = require_binary("ffmpeg")
    command, effective_audio_mode = build_ffmpeg_command(
        ffmpeg,
        silent_video,
        source,
        bgm,
        output,
        config["audio"]["mode"],
        float(config["audio"]["bgm_volume"]),
        bool(manifest["source"].get("has_audio")),
        args.crf,
        args.preset,
    )
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError("FFmpeg 封装失败: " + completed.stderr[-2000:])
    output_meta = probe_media(output)
    try:
        silent_video.unlink()
    except OSError:
        pass
    report = {
        "schema_version": 1,
        "created_at": utc_now(),
        "skill": "handframe-character-video",
        "project_dir": str(project),
        "output": output_meta,
        "render": {
            "frames": rendered,
            "fps": fps,
            "fit_mode": config["fit_mode"],
            "window_open_frames": window_open_frames,
            "window_closed_frames": rendered - window_open_frames,
            "first_window_open_time": None if first_window_open_time is None else round(first_window_open_time, 4),
            "track_source": "manual_keyframes" if config["keyframes"] else tracking["detector"]["mode"],
            "style_sequence": config["style_sequence"],
            "style_frame_counts": style_frame_counts,
            "style_transition_frames": transition_frame_count,
            "global_timeline_sync": True,
            "semantic_corner_order": ["left_index", "right_index", "right_thumb", "left_thumb"],
            "self_intersection_semantics": "semantic-fingertip-bow-tie",
            "self_intersection_frames": len(crossing_frame_times),
            "self_intersection_times": crossing_frame_times,
            "requested_audio_mode": config["audio"]["mode"],
            "effective_audio_mode": effective_audio_mode,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        },
        "evidence": {
            "review_confirmation_sha256": confirmation["config_sha256"],
            "source_identity_verified": True,
            "inside_identity_verified": True,
            "inside_count": len(inside_paths),
            "bgm_identity_verified": bgm is None or confirmation.get("bgm") is not None,
        },
        "missing_evidence": ["visual human review of final output"] if not config.get("review_notes") else [],
    }
    atomic_write_json(project / "render_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
