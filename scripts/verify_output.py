#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import itertools
from pathlib import Path

import cv2
import numpy as np

from common import atomic_write_json, corners_self_intersect, probe_media, read_json, utc_now, validate_review_config


VISUAL_DISTINCTNESS_THRESHOLD = 12.0


def mean_frame_delta(first: np.ndarray, second: np.ndarray) -> float:
    if first.shape[:2] != second.shape[:2]:
        second = cv2.resize(second, (first.shape[1], first.shape[0]), interpolation=cv2.INTER_AREA)
    return float(np.mean(np.abs(first.astype(np.float32) - second.astype(np.float32))))


def pairwise_visual_deltas(paths: list[Path], sample_fractions: tuple[float, ...] = (0.15, 0.325, 0.5, 0.675, 0.85)) -> list[dict[str, object]]:
    """Cheap pixel-level proxy; human review still decides whether character identities differ."""
    results: list[dict[str, object]] = []
    for first_index, second_index in itertools.combinations(range(len(paths)), 2):
        first, second = cv2.VideoCapture(str(paths[first_index])), cv2.VideoCapture(str(paths[second_index]))
        if not first.isOpened() or not second.isOpened():
            first.release(); second.release()
            raise RuntimeError("无法读取多风格视频以验证视觉差异")
        durations = []
        for capture in (first, second):
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 25.0)
            durations.append(float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 1) / fps)
        deltas: list[float] = []
        for fraction in sample_fractions:
            time_value = min(durations) * fraction
            first.set(cv2.CAP_PROP_POS_MSEC, time_value * 1000)
            second.set(cv2.CAP_PROP_POS_MSEC, time_value * 1000)
            ok_a, frame_a = first.read()
            ok_b, frame_b = second.read()
            if ok_a and ok_b:
                deltas.append(mean_frame_delta(frame_a, frame_b))
        first.release(); second.release()
        if not deltas:
            raise RuntimeError("多风格视觉差异验证没有取得有效采样帧")
        results.append({
            "pair": [first_index + 1, second_index + 1],
            "mean_absolute_pixel_delta": round(float(np.mean(deltas)), 3),
            "sample_deltas": [round(value, 3) for value in deltas],
        })
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证手势框成片的时长、分辨率、编码和产物合同")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--output", type=Path, help="默认读取项目目录 output.mp4")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project = args.project_dir.expanduser().resolve()
    manifest = read_json(project / "manifest.json")
    output = (args.output or (project / "output.mp4")).expanduser().resolve()
    required = [project / "tracking.json", project / "review_config.json", project / "review_confirmed.json", project / "render_report.json", output]
    inside_metas = manifest.get("insides") or [manifest["inside"]]
    inside_paths = [Path(item["path"]).expanduser().resolve() for item in inside_metas]
    inside_origins = manifest.get("inside_origins") or [manifest.get("inside_origin") or {}]
    if len(inside_origins) != len(inside_paths):
        raise ValueError("manifest 中 insides 与 inside_origins 数量不一致")
    ai_entries: list[tuple[int, dict, Path, Path, Path]] = []
    for index, (origin, inside_path) in enumerate(zip(inside_origins, inside_paths)):
        if origin.get("route") != "ai-video-edit":
            continue
        suffix = "" if len(inside_paths) == 1 else f"-{index + 1:02d}"
        request_path = Path(origin.get("request") or (project / f"transformation_request{suffix}.json")).expanduser().resolve()
        verification_path = Path(origin.get("verification") or (project / f"transform_verification{suffix}.json")).expanduser().resolve()
        ai_entries.append((index, origin, inside_path, request_path, verification_path))
        required.extend([inside_path, request_path, verification_path])
    missing = [str(path) for path in required if not path.is_file()]
    checks: list[dict[str, object]] = []
    if missing:
        checks.append({"name": "required_files", "ok": False, "detail": missing})
        result = {"ok": False, "created_at": utc_now(), "checks": checks}
        atomic_write_json(project / "verification.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    output_meta = probe_media(output)
    render_report = read_json(project / "render_report.json")
    render_info = render_report.get("render") or {}
    source_meta = manifest["source"]
    duration_delta = abs(float(output_meta["duration"]) - float(source_meta["duration"]))
    tolerance = max(0.25, 2 / max(1.0, float(source_meta.get("fps") or 25.0)))
    checks.extend(
        [
            {"name": "required_files", "ok": True, "detail": [path.name for path in required]},
            {"name": "duration", "ok": duration_delta <= tolerance, "detail": {"source": source_meta["duration"], "output": output_meta["duration"], "delta": duration_delta, "tolerance": tolerance}},
            {"name": "resolution", "ok": output_meta["width"] == source_meta["width"] and output_meta["height"] == source_meta["height"], "detail": {"source": [source_meta["width"], source_meta["height"]], "output": [output_meta["width"], output_meta["height"]]}},
            {"name": "video_codec", "ok": bool(output_meta.get("video_codec")), "detail": output_meta.get("video_codec")},
            {"name": "file_size", "ok": output.stat().st_size > 1024, "detail": output.stat().st_size},
            {"name": "aligned_mask_mode", "ok": render_info.get("fit_mode") == "clip", "detail": render_info.get("fit_mode")},
            {
                "name": "multi_style_global_timeline",
                "ok": bool(render_info.get("global_timeline_sync"))
                and int((render_report.get("evidence") or {}).get("inside_count", 1)) == len(inside_paths),
                "detail": {
                    "inside_count": len(inside_paths),
                    "reported_inside_count": (render_report.get("evidence") or {}).get("inside_count"),
                    "global_timeline_sync": render_info.get("global_timeline_sync"),
                    "style_sequence": render_info.get("style_sequence"),
                },
            },
            {
                "name": "window_visibility_accounted",
                "ok": int(render_info.get("window_open_frames", -1)) >= 0
                and int(render_info.get("window_closed_frames", -1)) >= 0
                and int(render_info.get("window_open_frames", -1)) + int(render_info.get("window_closed_frames", -1)) == int(render_info.get("frames", -2)),
                "detail": {
                    "open": render_info.get("window_open_frames"),
                    "closed": render_info.get("window_closed_frames"),
                    "first_open": render_info.get("first_window_open_time"),
                    "frames": render_info.get("frames"),
                },
            },
        ]
    )
    for index, origin, inside_path, request_path, verification_path in ai_entries:
        transform_request = read_json(request_path)
        transform_verification = read_json(verification_path)
        verified_output = transform_verification.get("output") or {}
        label = f"transform_{index + 1:02d}"
        checks.extend(
            [
                {"name": f"{label}_ai_route", "ok": origin.get("route") == "ai-video-edit", "detail": origin.get("route")},
                {
                    "name": f"{label}_explicit_style_selection",
                    "ok": transform_request.get("selection", {}).get("selection_source") == "user-explicit",
                    "detail": transform_request.get("selection", {}),
                },
                {
                    "name": f"{label}_no_gender_inference",
                    "ok": transform_request.get("selection", {}).get("gender_inference_performed") is False,
                    "detail": transform_request.get("selection", {}).get("gender_inference_performed"),
                },
                {
                    "name": f"{label}_automatic_checks",
                    "ok": transform_verification.get("automatic_checks_ok") is True,
                    "detail": transform_verification.get("checks"),
                },
                {
                    "name": f"{label}_identity",
                    "ok": Path(str(verified_output.get("path", ""))).expanduser().resolve() == inside_path,
                    "detail": {"inside": str(inside_path), "verified_output": verified_output.get("path")},
                },
            ]
        )
    style_counts = render_info.get("style_frame_counts") or []
    sequence = render_info.get("style_sequence") or {}
    checks.append(
        {
            "name": "multi_style_sequence_coverage",
            "ok": len(style_counts) == len(inside_paths)
            and (len(inside_paths) == 1 or not sequence.get("enabled") or all(int(value) > 0 for value in style_counts)),
            "detail": {"inside_count": len(inside_paths), "style_frame_counts": style_counts, "enabled": sequence.get("enabled")},
        }
    )
    config = validate_review_config(
        read_json(project / "review_config.json"),
        float(source_meta["duration"]),
        manifest.get("bgm") is not None,
        bool(ai_entries),
        len(inside_paths),
    )
    track_frames = config["keyframes"] if config["keyframes"] else read_json(project / "tracking.json")["frames"]
    crossed_keyframes = [round(float(frame["time"]), 4) for frame in track_frames if corners_self_intersect(frame.get("corners"))]
    reported_crossing_frames = int(render_info.get("self_intersection_frames", -1))
    checks.append(
        {
            "name": "semantic_rotation_crossing_preserved",
            "ok": render_info.get("semantic_corner_order") == ["left_index", "right_index", "right_thumb", "left_thumb"]
            and render_info.get("self_intersection_semantics") == "semantic-fingertip-bow-tie"
            and reported_crossing_frames >= 0
            and (not crossed_keyframes or reported_crossing_frames > 0),
            "detail": {
                "crossed_tracking_keyframes": len(crossed_keyframes),
                "crossed_tracking_times": crossed_keyframes,
                "rendered_crossing_frames": reported_crossing_frames,
                "rendered_crossing_times": render_info.get("self_intersection_times", []),
            },
        }
    )
    if len(inside_paths) > 1:
        pairwise = pairwise_visual_deltas(inside_paths)
        minimum = min(float(item["mean_absolute_pixel_delta"]) for item in pairwise)
        checks.append(
            {
                "name": "multi_style_pairwise_visual_distinctness_proxy",
                "ok": minimum >= VISUAL_DISTINCTNESS_THRESHOLD,
                "detail": {
                    "metric": "mean absolute pixel delta; proxy only, human identity/style review still required",
                    "threshold": VISUAL_DISTINCTNESS_THRESHOLD,
                    "minimum": round(minimum, 3),
                    "pairs": pairwise,
                },
            }
        )
    result = {"ok": all(bool(item["ok"]) for item in checks), "created_at": utc_now(), "output": output_meta, "checks": checks}
    atomic_write_json(project / "verification.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
