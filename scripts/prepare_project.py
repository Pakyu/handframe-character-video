#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from common import (
    SCHEMA_VERSION,
    atomic_write_json,
    default_quad,
    default_review_config,
    probe_media,
    read_json,
    utc_now,
)


SKILL_DIR = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="创建手势框视频项目并生成跟踪数据与审核页")
    parser.add_argument("--source", required=True, type=Path, help="原始视频")
    parser.add_argument("--inside", required=True, action="append", type=Path, help="框内视频；可重复传入多条全长对齐转绘片")
    parser.add_argument("--inside-label", action="append", help="对应转绘片的显示名称；可重复")
    parser.add_argument("--transform-request", action="append", type=Path, help="对应 transformation_request.json；可重复")
    parser.add_argument("--transform-verification", action="append", type=Path, help="对应 transform_verification.json；可重复")
    parser.add_argument("--bgm", type=Path, help="可选背景音乐")
    parser.add_argument("--output-dir", required=True, type=Path, help="新项目目录")
    parser.add_argument("--sample-fps", type=float, default=6.0, help="自动检测抽样帧率")
    parser.add_argument("--tracking-json", type=Path, help="导入同一原片先前已验证的 tracking.json，跳过重复检测")
    parser.add_argument("--manual-only", action="store_true", help="跳过 MediaPipe，直接进入人工模式")
    parser.add_argument("--require-detection", action="store_true", help="自动检测不可用或无有效双手时直接失败")
    parser.add_argument("--review-max-width", type=int, default=1280, help="审核代理最大宽度")
    return parser.parse_args()


def ensure_input(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label}不存在: {resolved}")
    return resolved


def browser_compatible(path: Path, meta: dict[str, Any], max_width: int) -> bool:
    return (
        path.suffix.lower() in {".mp4", ".m4v"}
        and meta.get("video_codec") == "h264"
        and meta.get("pixel_format") == "yuv420p"
        and int(meta.get("width") or 0) <= max_width
    )


def make_review_proxy(path: Path, meta: dict[str, Any], output: Path, max_width: int, keep_audio: bool) -> Path:
    if browser_compatible(path, meta, max_width):
        return path
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("需要生成浏览器审核代理，但找不到 ffmpeg")
    width, height = int(meta["width"]), int(meta["height"])
    target_width = min(max_width, width)
    target_width -= target_width % 2
    target_height = max(2, int(round(height * target_width / width)))
    target_height -= target_height % 2
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(path),
        "-map",
        "0:v:0",
    ]
    if keep_audio:
        command += ["-map", "0:a:0?"]
    command += [
        "-vf",
        f"scale={target_width}:{target_height}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
    ]
    if keep_audio:
        command += ["-c:a", "aac", "-b:a", "128k"]
    else:
        command += ["-an"]
    command += ["-movflags", "+faststart", str(output)]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError("审核代理生成失败: " + completed.stderr[-1500:])
    return output


def polygon_area(points: np.ndarray) -> float:
    hull = cv2.convexHull(points.astype(np.float32))
    return float(cv2.contourArea(hull))


def stabilize_thin_quad(candidate: np.ndarray, min_thickness: float = 0.006) -> np.ndarray:
    candidate = np.clip(candidate.astype(np.float32), 0.0, 1.0)
    if polygon_area(candidate) >= 0.0015:
        return candidate
    left = (candidate[0] + candidate[3]) / 2
    right = (candidate[1] + candidate[2]) / 2
    direction = right - left
    length = float(np.linalg.norm(direction))
    if length < 1e-5:
        direction = np.array([1.0, 0.0], dtype=np.float32)
        length = 1.0
    normal = np.array([-direction[1], direction[0]], dtype=np.float32) / length
    top = (candidate[0] + candidate[1]) / 2
    bottom = (candidate[2] + candidate[3]) / 2
    if float(np.dot(top - bottom, normal)) < 0:
        normal = -normal
    actual = abs(float(np.dot(top - bottom, normal)))
    required_thickness = 0.0015 / max(length, 0.03)
    half = max(min_thickness / 2, required_thickness / 2, actual / 2)
    stabilized = np.array(
        [left + normal * half, right + normal * half, right - normal * half, left - normal * half],
        dtype=np.float32,
    )
    stabilized = np.clip(stabilized, 0.0, 1.0)
    return stabilized


def smooth_tracking_segment(
    frames: list[dict[str, Any]],
    start: float,
    end: float,
    ramp: float = 0.5,
) -> list[dict[str, Any]]:
    """Remove corner-ID flips and local spikes while tapering into untouched motion."""
    if not frames or end <= start:
        return frames
    aligned: list[np.ndarray] = []
    previous: np.ndarray | None = None
    for frame in frames:
        quad = np.array(frame["corners"], dtype=np.float32)
        aligned.append(quad)
        previous = quad
    values = np.stack(aligned)
    times = np.array([float(frame["time"]) for frame in frames], dtype=np.float32)
    median = values.copy()
    for index, time_value in enumerate(times):
        if start - ramp <= time_value <= end + ramp:
            median[index] = np.median(values[max(0, index - 2): min(len(values), index + 3)], axis=0)
    filtered = median.copy()
    weights = np.array([1, 2, 3, 2, 1], dtype=np.float32)
    for index, time_value in enumerate(times):
        if start - ramp <= time_value <= end + ramp:
            indices = np.arange(max(0, index - 2), min(len(values), index + 3))
            local_weights = weights[(indices - index) + 2]
            filtered[index] = np.average(median[indices], axis=0, weights=local_weights)
    output: list[dict[str, Any]] = []
    ramp = max(0.01, float(ramp))
    for index, frame in enumerate(frames):
        time_value = float(times[index])
        if start <= time_value <= end:
            phase = min(1.0, (time_value - start) / ramp, (end - time_value) / ramp)
            phase = max(0.0, phase)
            alpha = 0.5 - 0.5 * math.cos(math.pi * phase)
            quad = values[index] * (1 - alpha) + filtered[index] * alpha
        else:
            quad = values[index]
        item = dict(frame)
        item["corners"] = [[round(float(x), 6), round(float(y), 6)] for x, y in quad]
        output.append(item)
    return output


def detect_tracking(source: Path, meta: dict[str, Any], sample_fps: float) -> dict[str, Any]:
    try:
        import mediapipe as mp
    except Exception as exc:
        raise RuntimeError(f"MediaPipe 不可用: {exc}") from exc

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV 无法打开视频: {source}")
    source_fps = float(capture.get(cv2.CAP_PROP_FPS) or meta.get("fps") or 25.0)
    sample_fps = max(0.5, min(sample_fps, source_fps))
    step = max(1, int(round(source_fps / sample_fps)))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(meta["width"])
    height = int(meta["height"])
    default = np.array(default_quad(), dtype=np.float32)
    last: np.ndarray | None = None
    lost = 0
    max_lost = max(1, int(round(sample_fps * 0.6)))
    frames: list[dict[str, Any]] = []
    detected_count = 0
    held_count = 0
    phase_counts = {"line": 0, "opening": 0, "open": 0, "held": 0, "absent": 0}

    with mp.solutions.hands.Hands(
        static_image_mode=False,
        max_num_hands=2,
        min_detection_confidence=0.3,
        min_tracking_confidence=0.3,
        model_complexity=1,
    ) as hands:
        index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if index % step:
                index += 1
                continue
            time_value = index / source_fps
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = hands.process(rgb)
            target: np.ndarray | None = None
            confidence = 0.0
            if result.multi_hand_landmarks and len(result.multi_hand_landmarks) == 2:
                info = []
                for hand in result.multi_hand_landmarks:
                    landmarks = hand.landmark
                    wrist = np.array([landmarks[0].x, landmarks[0].y], dtype=np.float32)
                    thumb = np.array([landmarks[4].x, landmarks[4].y], dtype=np.float32)
                    index_tip = np.array([landmarks[8].x, landmarks[8].y], dtype=np.float32)
                    middle_mcp = np.array([landmarks[9].x, landmarks[9].y], dtype=np.float32)
                    scale = float(np.linalg.norm(wrist - middle_mcp)) + 1e-6
                    spread = float(np.linalg.norm(thumb - index_tip)) / scale
                    info.append({"wrist_x": float(wrist[0]), "thumb": thumb, "index": index_tip, "spread": spread})
                info.sort(key=lambda item: item["wrist_x"])
                left, right = info
                candidate = np.array(
                    [left["index"], right["index"], right["thumb"], left["thumb"]],
                    dtype=np.float32,
                )
                raw_area = polygon_area(candidate)
                target = stabilize_thin_quad(candidate)
                confidence = max(0.15, min(1.0, raw_area / 0.08))
                if raw_area < 0.005:
                    gesture_phase = "line"
                elif raw_area < 0.015:
                    gesture_phase = "opening"
                else:
                    gesture_phase = "open"
            if target is not None:
                if last is None:
                    current = target
                else:
                    moved = float(np.mean(np.linalg.norm(target - last, axis=1)))
                    alpha = min(0.85, max(0.35, moved / 0.05))
                    current = last * (1 - alpha) + target * alpha
                last = current
                lost = 0
                detected_count += 1
                source_kind = "detected"
            elif last is not None and lost < max_lost:
                lost += 1
                current = last
                confidence = max(0.1, 0.5 * (1 - lost / (max_lost + 1)))
                held_count += 1
                source_kind = "held"
                gesture_phase = "held"
            else:
                current = default
                confidence = 0.0
                source_kind = "default"
                gesture_phase = "absent"
                last = None
                lost = 0
            phase_counts[gesture_phase] += 1
            frames.append(
                {
                    "time": round(time_value, 4),
                    "corners": [[round(float(x), 6), round(float(y), 6)] for x, y in current],
                    "confidence": round(confidence, 4),
                    "source": source_kind,
                    "visible": source_kind in {"detected", "held"},
                    "gesture_phase": gesture_phase,
                }
            )
            index += 1
    capture.release()
    if not frames:
        frames = [{"time": 0.0, "corners": default_quad(), "confidence": 0.0, "source": "default", "visible": False, "gesture_phase": "absent"}]
    coverage = detected_count / max(1, len(frames))
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "source_size": [width, height],
        "duration": meta["duration"],
        "sample_fps": sample_fps,
        "detector": {"name": "mediapipe-solutions-hands", "mode": "automatic"},
        "frames": frames,
        "stats": {
            "sampled_frames": len(frames),
            "detected_frames": detected_count,
            "held_frames": held_count,
            "phase_counts": phase_counts,
            "detection_coverage": round(coverage, 4),
        },
        "needs_manual_review": coverage < 0.5,
    }


def manual_tracking(meta: dict[str, Any], reason: str) -> dict[str, Any]:
    duration = float(meta["duration"])
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "source_size": [meta["width"], meta["height"]],
        "duration": duration,
        "sample_fps": 0,
        "detector": {"name": "manual-default", "mode": "manual", "reason": reason},
        "frames": [
            {"time": 0.0, "corners": default_quad(), "confidence": 0.0, "source": "default", "visible": False, "gesture_phase": "absent"},
            {"time": duration, "corners": default_quad(), "confidence": 0.0, "source": "default", "visible": False, "gesture_phase": "absent"},
        ],
        "stats": {"sampled_frames": 0, "detected_frames": 0, "held_frames": 0, "phase_counts": {"line": 0, "opening": 0, "open": 0, "held": 0, "absent": 2}, "detection_coverage": 0.0},
        "needs_manual_review": True,
    }


def imported_tracking(path: Path, meta: dict[str, Any]) -> dict[str, Any]:
    tracking = read_json(path)
    source_size = [int(meta["width"]), int(meta["height"])]
    if [int(value) for value in tracking.get("source_size", [])] != source_size:
        raise ValueError("导入 tracking.json 的 source_size 与当前原片不一致")
    if abs(float(tracking.get("duration", -1)) - float(meta["duration"])) > 0.15:
        raise ValueError("导入 tracking.json 的时长与当前原片不一致")
    frames = tracking.get("frames") or []
    if not frames or any(float(frame.get("time", -1)) < 0 for frame in frames):
        raise ValueError("导入 tracking.json 缺少有效帧")
    if any(float(frames[index]["time"]) > float(frames[index + 1]["time"]) for index in range(len(frames) - 1)):
        raise ValueError("导入 tracking.json 的时间轴无序")
    imported = dict(tracking)
    imported["created_at"] = utc_now()
    imported["detector"] = {
        "name": str((tracking.get("detector") or {}).get("name") or "imported-tracking"),
        "mode": "imported-verified",
        "source_tracking": str(path.resolve()),
    }
    imported["needs_manual_review"] = bool(tracking.get("needs_manual_review", True))
    return imported


def main() -> int:
    args = parse_args()
    source = ensure_input(args.source, "原始视频")
    insides = [ensure_input(path, f"框内视频 {index + 1}") for index, path in enumerate(args.inside)]
    if bool(args.transform_request) != bool(args.transform_verification):
        raise ValueError("--transform-request 与 --transform-verification 必须同时提供")
    if args.transform_request and (len(args.transform_request) != len(insides) or len(args.transform_verification) != len(insides)):
        raise ValueError("每条 --inside 都必须对应一个 --transform-request 和 --transform-verification")
    if args.inside_label and len(args.inside_label) > len(insides):
        raise ValueError("--inside-label 数量不能超过 --inside 数量")
    labels: list[str | None] = list(args.inside_label or [])
    labels += [None for _ in range(len(labels), len(insides))]
    bgm = ensure_input(args.bgm, "背景音乐") if args.bgm else None
    output = args.output_dir.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"输出目录不是空目录: {output}")
    output.mkdir(parents=True, exist_ok=True)

    source_meta = probe_media(source)
    inside_origins: list[dict[str, Any]] = []
    if args.transform_request and args.transform_verification:
        for index, inside in enumerate(insides):
            request_path = ensure_input(args.transform_request[index], f"转绘请求 {index + 1}")
            verification_path = ensure_input(args.transform_verification[index], f"转绘验证报告 {index + 1}")
            request, verification = read_json(request_path), read_json(verification_path)
            if verification.get("automatic_checks_ok") is not True:
                raise RuntimeError(f"转绘视频 {index + 1} 没有通过自动媒体检查")
            verified_output = Path(verification.get("output", {}).get("path", "")).expanduser().resolve()
            if verified_output != inside:
                raise RuntimeError(f"转绘验证报告 {index + 1} 与对应 --inside 不是同一文件")
            suffix = "" if len(insides) == 1 else f"-{index + 1:02d}"
            project_request = output / f"transformation_request{suffix}.json"
            project_verification = output / f"transform_verification{suffix}.json"
            shutil.copy2(request_path, project_request)
            shutil.copy2(verification_path, project_verification)
            inside_origins.append({
                "route": "ai-video-edit", "generated_from_source": True,
                "style_id": request.get("selection", {}).get("style_id"),
                "display_name": labels[index] or request.get("selection", {}).get("display_name") or f"转绘风格 {index + 1}",
                "selection_source": request.get("selection", {}).get("selection_source"),
                "gender_inference_performed": request.get("selection", {}).get("gender_inference_performed"),
                "provider": str(verification.get("provider", {}).get("name") or "unknown"),
                "request": str(project_request.resolve()), "verification": str(project_verification.resolve()),
                "human_review_required": True,
            })
    else:
        inside_origins = [
            {
                "route": "user-supplied",
                "generated_from_source": False,
                "display_name": labels[index] or f"转绘风格 {index + 1}",
            }
            for index in range(len(insides))
        ]
    inside_metas = [probe_media(inside) for inside in insides]
    review_source = make_review_proxy(source, source_meta, output / "review_source.mp4", max(320, args.review_max_width), True)
    review_insides = [make_review_proxy(inside, inside_metas[index], output / f"review_inside_{index + 1:02d}.mp4", max(320, args.review_max_width), False) for index, inside in enumerate(insides)]
    bgm_meta = None
    if bgm:
        try:
            bgm_meta = probe_media(bgm)
        except RuntimeError:
            bgm_meta = {"path": str(bgm), "size_bytes": bgm.stat().st_size, "audio_only": True}

    detection_error = None
    if args.tracking_json:
        tracking_path = ensure_input(args.tracking_json, "导入跟踪文件")
        tracking = imported_tracking(tracking_path, source_meta)
        if args.require_detection and int((tracking.get("stats") or {}).get("detected_frames", 0)) == 0:
            raise RuntimeError("导入的跟踪文件没有有效双手检测帧")
    elif args.manual_only:
        tracking = manual_tracking(source_meta, "manual-only requested")
    else:
        try:
            tracking = detect_tracking(source, source_meta, args.sample_fps)
            if tracking["stats"]["detected_frames"] == 0 and args.require_detection:
                raise RuntimeError("自动检测没有找到有效双手取景框")
        except Exception as exc:
            detection_error = str(exc)
            if args.require_detection:
                raise
            tracking = manual_tracking(source_meta, detection_error)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "skill": "handframe-character-video",
        "source": source_meta,
        "inside": inside_metas[0],
        "insides": inside_metas,
        "inside_origin": inside_origins[0],
        "inside_origins": inside_origins,
        "bgm": bgm_meta,
        "review_media": {
            "source": str(review_source.resolve()),
            "inside": str(review_insides[0].resolve()),
            "insides": [str(path.resolve()) for path in review_insides],
            "source_is_proxy": review_source.resolve() != source.resolve(),
            "inside_is_proxy": review_insides[0].resolve() != insides[0].resolve(),
            "inside_proxy_flags": [review_insides[index].resolve() != insides[index].resolve() for index in range(len(insides))],
        },
        "permissions": {
            "camera": False,
            "media_upload": any(origin.get("route") == "ai-video-edit" and origin.get("provider") not in {"recorded-fixture", "manual-local"} for origin in inside_origins),
            "network_used_by_prepare": False,
            "external_generation_before_prepare": any(origin.get("route") == "ai-video-edit" for origin in inside_origins),
            "source_files_mutated": False,
        },
        "detection": {
            "mode": tracking["detector"]["mode"],
            "error": detection_error,
            "needs_manual_review": tracking["needs_manual_review"],
        },
    }
    atomic_write_json(output / "manifest.json", manifest)
    atomic_write_json(output / "tracking.json", tracking)
    open_frames = [frame for frame in tracking["frames"] if frame.get("gesture_phase") == "open"]
    sequence_start_seconds = float(open_frames[0]["time"]) if open_frames else 0.0
    atomic_write_json(
        output / "review_config.json",
        default_review_config(
            source_meta["duration"],
            bgm is not None,
            any(origin.get("route") == "ai-video-edit" for origin in inside_origins),
            len(insides),
            sequence_start_seconds,
        ),
    )
    shutil.copy2(SKILL_DIR / "assets" / "review.html", output / "review.html")
    print(
        {
            "project_dir": str(output),
            "tracking": str(output / "tracking.json"),
            "review": str(output / "review.html"),
            "needs_manual_review": tracking["needs_manual_review"],
            "detection_coverage": tracking["stats"]["detection_coverage"],
        }
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
