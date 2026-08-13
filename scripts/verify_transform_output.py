#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from common import atomic_write_json, file_identity, probe_media, read_json, utc_now


def frame_at(path: Path, time_value: float) -> np.ndarray:
    capture = cv2.VideoCapture(str(path))
    capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, time_value) * 1000.0)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError(f"无法读取验证帧: {path} @ {time_value:.3f}s")
    return frame


def visual_delta(source: Path, transformed: Path, source_duration: float, transformed_duration: float) -> float:
    values: list[float] = []
    for fraction in (0.1, 0.3, 0.5, 0.7, 0.9):
        first = frame_at(source, max(0.0, source_duration * fraction - 0.01))
        second = frame_at(transformed, max(0.0, transformed_duration * fraction - 0.01))
        second = cv2.resize(second, (first.shape[1], first.shape[0]), interpolation=cv2.INTER_AREA)
        values.append(float(np.mean(np.abs(first.astype(np.int16) - second.astype(np.int16)))))
    return float(np.mean(values))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证视频转绘产物的媒体合同并生成必须人工复核的报告")
    parser.add_argument("--request", required=True, type=Path, help="transformation_request.json")
    parser.add_argument("--video", required=True, type=Path, help="生成的转绘视频")
    parser.add_argument("--output", type=Path, help="默认写到请求目录 transform_verification.json")
    parser.add_argument("--provider", default="unknown")
    parser.add_argument("--thread-id")
    parser.add_argument("--run-id")
    parser.add_argument("--web-link")
    parser.add_argument("--external-confirmed", action="store_true", help="仅在用户已明确同意上传与 credits 消耗后传入")
    parser.add_argument("--manual-return", action="store_true", help="用户已在外部平台手动生成并回传；允许本地媒体 QA，但明确缺少 Provider trace")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    request_path = args.request.expanduser().resolve()
    video = args.video.expanduser().resolve()
    request = read_json(request_path)
    source = Path(request["source"]["path"]).expanduser().resolve()
    if not source.is_file() or not video.is_file():
        raise FileNotFoundError("原片或转绘视频不存在")
    source_meta = probe_media(source)
    transformed_meta = probe_media(video)
    duration_tolerance = max(0.5, float(source_meta["duration"]) * 0.10)
    duration_delta = abs(float(source_meta["duration"]) - float(transformed_meta["duration"]))
    source_ratio = float(source_meta["width"]) / max(1.0, float(source_meta["height"]))
    output_ratio = float(transformed_meta["width"]) / max(1.0, float(transformed_meta["height"]))
    delta = visual_delta(source, video, float(source_meta["duration"]), float(transformed_meta["duration"]))
    fixture_provider = args.provider in {"recorded-fixture", "manual-local"}
    provider_backed = bool(args.thread_id and args.run_id) and not fixture_provider and not args.manual_return
    provider_trace_ok = fixture_provider or args.manual_return or provider_backed
    external_confirmation_ok = fixture_provider or args.manual_return or args.external_confirmed
    checks = [
        {"name": "explicit_style_selection", "ok": request.get("selection", {}).get("selection_source") == "user-explicit"},
        {"name": "no_gender_inference", "ok": request.get("selection", {}).get("gender_inference_performed") is False},
        {"name": "duration", "ok": duration_delta <= duration_tolerance, "detail": {"delta": duration_delta, "tolerance": duration_tolerance}},
        {"name": "aspect_ratio", "ok": abs(source_ratio - output_ratio) <= 0.08, "detail": {"source": source_ratio, "output": output_ratio}},
        {"name": "video_codec", "ok": bool(transformed_meta.get("video_codec")), "detail": transformed_meta.get("video_codec")},
        {"name": "visual_change", "ok": delta >= 4.0, "detail": round(delta, 3)},
        {"name": "file_size", "ok": video.stat().st_size > 1024, "detail": video.stat().st_size},
        {"name": "external_confirmation", "ok": external_confirmation_ok, "detail": "manual return; no new upload performed" if args.manual_return else bool(args.external_confirmed)},
        {"name": "provider_trace", "ok": provider_trace_ok, "detail": {"provider": args.provider, "thread_id": args.thread_id, "run_id": args.run_id, "status": "missing evidence" if args.manual_return else "available" if provider_backed else "fixture"}},
    ]
    automatic_ok = all(bool(item["ok"]) for item in checks)
    result = {
        "schema_version": 1,
        "created_at": utc_now(),
        "ok": automatic_ok,
        "automatic_checks_ok": automatic_ok,
        "human_review_required": True,
        "request": str(request_path),
        "source": source_meta,
        "output": transformed_meta,
        "output_identity": file_identity(video),
        "provider": {"name": args.provider, "thread_id": args.thread_id, "run_id": args.run_id, "web_link": args.web_link, "external_confirmation_recorded": external_confirmation_ok, "provider_backed": provider_backed, "manual_return": bool(args.manual_return)},
        "checks": checks,
        "human_checklist": [
            "角色或画面风格与用户明确选择一致。",
            "人物数量、动作、口型、镜头、构图与原片基本一致。",
            "原片与转绘片逐帧全画面对齐；头、脸、双手、手指、身体轮廓和背景结构位于同一画面坐标，可直接通过动态遮罩切换。",
            "脸、手、肢体、服装和遮罩在时间上稳定，无闪烁或漂移。",
            "没有新增或消失人物，没有文字、字幕、品牌字样或水印。",
            "确认角色为原创设计，未出现现有 IP 名称、标志、经典配色或可识别精确设计。",
        ],
        "missing_evidence": (["provider task id, run id, model page, and credits record"] if args.manual_return else []) + ["human visual approval"],
    }
    output = args.output.expanduser().resolve() if args.output else request_path.parent / "transform_verification.json"
    atomic_write_json(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if automatic_ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
