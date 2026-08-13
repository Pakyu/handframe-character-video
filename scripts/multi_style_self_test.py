#!/usr/bin/env python3
from __future__ import annotations

import json
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

from common import atomic_write_json, file_identity, json_sha256, read_json, utc_now, validate_review_config


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行多转绘视频全局时间线与顺序轮换的合成夹具测试")
    return parser.parse_args()


def run(*args: str) -> None:
    completed = subprocess.run([sys.executable, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode:
        raise RuntimeError(completed.stderr or completed.stdout)


def make_video(path: Path, color: tuple[int, int, int], seconds: float = 2.0, fps: int = 15) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 180))
    if not writer.isOpened():
        raise RuntimeError(f"无法创建测试视频: {path}")
    for index in range(round(seconds * fps)):
        frame = np.full((180, 320, 3), color, dtype=np.uint8)
        cv2.rectangle(frame, (15 + index * 4, 20), (23 + index * 4, 160), (245, 245, 245), -1)
        writer.write(frame)
    writer.release()


def center_pixel(video: Path, time_value: float) -> list[int]:
    capture = cv2.VideoCapture(str(video))
    capture.set(cv2.CAP_PROP_POS_MSEC, time_value * 1000)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError(f"无法读取测试成片 {time_value}s")
    return [int(value) for value in frame[90, 160]]


def main() -> int:
    parse_args()
    with tempfile.TemporaryDirectory(prefix="handframe-multi-style-selftest-") as temporary:
        root = Path(temporary)
        source = root / "source.mp4"
        insides = [root / f"inside-{index + 1}.mp4" for index in range(3)]
        make_video(source, (8, 8, 8))
        colors = [(20, 20, 230), (20, 220, 20), (220, 20, 20)]
        for path, color in zip(insides, colors):
            make_video(path, color)

        project = root / "project"
        command = [str(SCRIPTS / "prepare_project.py"), "--source", str(source)]
        for index, path in enumerate(insides):
            command += ["--inside", str(path), "--inside-label", f"测试角色 {index + 1}"]
        command += ["--output-dir", str(project), "--manual-only"]
        run(*command)

        tracking = read_json(project / "tracking.json")
        quad = [[0.02, 0.02], [0.98, 0.02], [0.98, 0.98], [0.02, 0.98]]
        tracking["frames"] = [
            {"time": 0.0, "corners": quad, "confidence": 1.0, "source": "detected", "visible": True, "gesture_phase": "open"},
            {"time": 2.0, "corners": quad, "confidence": 1.0, "source": "detected", "visible": True, "gesture_phase": "open"},
        ]
        atomic_write_json(project / "tracking.json", tracking)

        config = read_json(project / "review_config.json")
        config["audio"]["mode"] = "none"
        config["style_sequence"] = {
            "enabled": True,
            "start_seconds": 0.25,
            "segment_seconds": 0.5,
            "transition_seconds": 0.05,
            "order": [0, 1, 2],
            "global_timeline": True,
            "loop_order": False,
        }
        config = validate_review_config(config, 2.0, False, False, 3)
        atomic_write_json(project / "review_config.json", config)
        atomic_write_json(
            project / "review_confirmed.json",
            {
                "schema_version": 1,
                "confirmed_at": utc_now(),
                "instance_id": "multi-style-self-test",
                "config_sha256": json_sha256(config),
                "source": file_identity(source),
                "inside": file_identity(insides[0]),
                "insides": [file_identity(path) for path in insides],
                "bgm": None,
            },
        )
        run(str(SCRIPTS / "render_video.py"), str(project))
        run(str(SCRIPTS / "verify_output.py"), str(project))

        report = read_json(project / "render_report.json")
        verification = read_json(project / "verification.json")
        pixels = [center_pixel(project / "output.mp4", value) for value in (0.5, 1.0, 1.5)]
        dominant = [int(np.argmax(pixel)) for pixel in pixels]
        checks = {
            "all_styles_receive_frames": all(value > 0 for value in report["render"]["style_frame_counts"]),
            "global_timeline_sync": report["render"]["global_timeline_sync"] is True,
            "sequence_start_preserved": report["render"]["style_sequence"]["start_seconds"] == 0.25,
            "ordered_switches_and_last_style_hold": dominant == [2, 1, 0],
            "final_verification": verification["ok"] is True,
        }
        result = {
            "evidence_type": "synthetic_multi_style_end_to_end",
            "ok": all(checks.values()),
            "checks": checks,
            "style_frame_counts": report["render"]["style_frame_counts"],
            "sample_center_pixels_bgr": pixels,
            "limitations": [
                "synthetic color clips; not evidence of Seedance character quality",
                "manual full-frame tracking; not evidence of hand detection quality",
                "visual character distinctness still requires human review of real transformed videos",
            ],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
