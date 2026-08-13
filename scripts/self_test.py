#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行不依赖摄像头或 MediaPipe 的端到端回归测试")
    parser.add_argument("--keep", type=Path, help="保留测试项目到指定目录")
    parser.add_argument("--evidence-output", type=Path, help="写出 recorded_fixture 证据 JSON")
    return parser.parse_args()


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")


def make_video(path: Path, kind: str, seconds: float = 2.0, fps: float = 15.0, size: tuple[int, int] = (320, 180), browser_compatible: bool = True) -> None:
    width, height = size
    raw_path = path.with_name(path.stem + ".raw.mp4")
    writer = cv2.VideoWriter(str(raw_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not writer.isOpened():
        raise RuntimeError("测试视频编码器不可用")
    for index in range(int(seconds * fps)):
        t = index / fps
        yy, xx = np.indices((height, width))
        if kind == "source":
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[..., 0] = (xx * 255 / width).astype(np.uint8)
            frame[..., 1] = (yy * 180 / height).astype(np.uint8)
            cv2.circle(frame, (int(width * (0.2 + 0.6 * t / seconds)), height // 2), 24, (30, 230, 240), -1)
            cv2.putText(frame, "SOURCE", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        else:
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[..., 2] = (150 + 100 * np.sin((xx + index * 5) / 25)).clip(0, 255).astype(np.uint8)
            frame[..., 1] = (80 + 80 * np.cos((yy + index * 3) / 18)).clip(0, 255).astype(np.uint8)
            for x in range(0, width, 32):
                cv2.line(frame, (x, 0), (x, height), (255, 80, 30), 2)
            cv2.putText(frame, "INSIDE", (width - 100, height - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        writer.write(frame)
    writer.release()
    if not browser_compatible:
        raw_path.replace(path)
        return
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("self-test 缺少 ffmpeg")
    completed = subprocess.run(
        [ffmpeg, "-y", "-i", str(raw_path), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError("测试视频 H.264 转码失败: " + completed.stderr[-1000:])
    raw_path.unlink(missing_ok=True)


def http_json(url: str, payload: dict | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict, dict[str, str]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"} if payload is not None else {}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=request_headers, method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read()
        parsed = json.loads(body.decode("utf-8")) if body else {}
        return response.status, parsed, dict(response.headers.items())


def media_frame(path: Path, time_value: float) -> np.ndarray:
    capture = cv2.VideoCapture(str(path))
    capture.set(cv2.CAP_PROP_POS_MSEC, time_value * 1000)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError(f"无法读取验证帧: {path}")
    return frame


def execute(root: Path) -> dict:
    source = root / "source.mp4"
    inside = root / "inside.mp4"
    project = root / "project"
    make_video(source, "source")
    make_video(inside, "inside")
    legacy_source = root / "legacy_source.mp4"
    make_video(legacy_source, "source", seconds=0.6, browser_compatible=False)
    proxy_project = root / "proxy_project"
    proxy_prepare = run([sys.executable, str(SCRIPT_DIR / "prepare_project.py"), "--source", str(legacy_source), "--inside", str(inside), "--output-dir", str(proxy_project), "--manual-only"])
    proxy_manifest = json.loads((proxy_project / "manifest.json").read_text(encoding="utf-8"))
    proxy_path = Path(proxy_manifest["review_media"]["source"])
    if not proxy_manifest["review_media"]["source_is_proxy"] or not proxy_path.is_file():
        raise RuntimeError("浏览器不兼容输入没有生成审核代理")
    transform_dir = root / "transform"
    request_prepare = run(
        [
            sys.executable,
            str(SCRIPT_DIR / "prepare_transform_request.py"),
            "--source",
            str(source),
            "--style-id",
            "original-urban-comic-hero",
            "--usage",
            "personal",
            "--output-dir",
            str(transform_dir),
        ]
    )
    transform_request = transform_dir / "transformation_request.json"
    transform_verification = transform_dir / "transform_verification.json"
    transform_verify = run(
        [
            sys.executable,
            str(SCRIPT_DIR / "verify_transform_output.py"),
            "--request",
            str(transform_request),
            "--video",
            str(inside),
            "--provider",
            "recorded-fixture",
            "--output",
            str(transform_verification),
        ]
    )
    prepare = run(
        [
            sys.executable,
            str(SCRIPT_DIR / "prepare_project.py"),
            "--source",
            str(source),
            "--inside",
            str(inside),
            "--transform-request",
            str(transform_request),
            "--transform-verification",
            str(transform_verification),
            "--output-dir",
            str(project),
            "--manual-only",
        ]
    )
    project_manifest = json.loads((project / "manifest.json").read_text(encoding="utf-8"))
    if project_manifest.get("inside_origin", {}).get("route") != "ai-video-edit":
        raise RuntimeError("转绘路线没有记录 ai-video-edit 来源")
    if project_manifest.get("inside_origin", {}).get("gender_inference_performed") is not False:
        raise RuntimeError("转绘路线意外执行或记录了性别推断")
    if not (project / "transformation_request.json").is_file() or not (project / "transform_verification.json").is_file():
        raise RuntimeError("项目没有保存转绘请求或验证报告")
    fixture_tracking = json.loads((project / "tracking.json").read_text(encoding="utf-8"))
    for frame in fixture_tracking["frames"]:
        frame["source"] = "detected"
        frame["confidence"] = 1.0
        frame["visible"] = True
    fixture_tracking["stats"] = {
        "sampled_frames": len(fixture_tracking["frames"]),
        "detected_frames": len(fixture_tracking["frames"]),
        "held_frames": 0,
        "visible_frames": len(fixture_tracking["frames"]),
        "detection_coverage": 1.0,
    }
    fixture_tracking["needs_manual_review"] = False
    (project / "tracking.json").write_text(json.dumps(fixture_tracking, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    server = subprocess.Popen(
        [sys.executable, str(SCRIPT_DIR / "review_server.py"), str(project), "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        status_path = project / "review_server_status.json"
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and not status_path.is_file():
            if server.poll() is not None:
                out, err = server.communicate()
                raise RuntimeError(f"审核服务提前退出: {out}\n{err}")
            time.sleep(0.1)
        if not status_path.is_file():
            raise TimeoutError("审核服务没有生成状态文件")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        base = f"http://127.0.0.1:{status['port']}"
        status_code, api_status, _ = http_json(base + "/api/status")
        if status_code != 200 or api_status["instance_id"] != status["instance_id"]:
            raise RuntimeError("审核服务身份校验失败")
        range_request = urllib.request.Request(base + "/media/source", headers={"Range": "bytes=0-99"})
        with urllib.request.urlopen(range_request, timeout=10) as response:
            review_source_size = int(status.get("review_source", status["source"])["size_bytes"])
            range_ok = response.status == 206 and response.headers.get("Content-Range", "").endswith(f"/{review_source_size}") and len(response.read()) == 100
        if not range_ok:
            raise RuntimeError("视频 Range 校验失败")
        _, project_data, _ = http_json(base + "/api/project")
        config = project_data["config"]
        duration = float(project_data["manifest"]["source"]["duration"])
        config["fit_mode"] = "clip"
        config["keyframes"] = [
            {"time": 0.0, "corners": [[0.2, 0.2], [0.8, 0.18], [0.78, 0.8], [0.22, 0.78]]},
            {"time": duration, "corners": [[0.26, 0.24], [0.76, 0.22], [0.82, 0.76], [0.18, 0.74]]},
        ]
        config["effects"] = [{"type": "rgb", "start": 0.6, "end": 1.2, "intensity": 0.7}]
        config["audio"] = {"mode": "none", "bgm_volume": 0.35, "available": False}
        config["review_notes"] = "self-test recorded fixture"
        config["transform_review"] = {"required": True, "approved": False}
        config["transform_reviews"] = [{"index": 0, "approved": False}]
        transform_gate_rejected = False
        try:
            http_json(base + "/api/confirm", {"instance_id": status["instance_id"], "config": config})
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            transform_gate_rejected = exc.code == 400 and "AI 转绘视频" in str(body.get("error", ""))
        if not transform_gate_rejected:
            raise RuntimeError("未勾选 AI 转绘接受时，审核服务没有阻断确认")
        config["transform_review"] = {"required": True, "approved": True}
        config["transform_reviews"] = [{"index": 0, "approved": True}]
        confirm_code, confirm, _ = http_json(base + "/api/confirm", {"instance_id": status["instance_id"], "config": config})
        if confirm_code != 200 or not confirm.get("confirmed"):
            raise RuntimeError("审核确认接口失败")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    watch = run([sys.executable, str(SCRIPT_DIR / "watch_review.py"), str(project), "--timeout", "5"])
    render = run([sys.executable, str(SCRIPT_DIR / "render_video.py"), str(project), "--preset", "veryfast", "--crf", "22"])
    verify = run([sys.executable, str(SCRIPT_DIR / "verify_output.py"), str(project)])
    output = project / "output.mp4"
    source_frame = media_frame(source, 1.0)
    styled_frame = media_frame(inside, 1.0)
    output_frame = media_frame(output, 1.0)
    transform_delta = float(np.mean(np.abs(source_frame.astype(np.int16) - styled_frame.astype(np.int16))))
    if transform_delta < 8.0:
        raise RuntimeError(f"转绘夹具与原片差异过小: {transform_delta:.3f}")
    visual_delta = float(np.mean(np.abs(source_frame.astype(np.int16) - output_frame.astype(np.int16))))
    if visual_delta < 8.0:
        raise RuntimeError(f"合成帧与源视频差异过小: {visual_delta:.3f}")
    verification = json.loads((project / "verification.json").read_text(encoding="utf-8"))
    return {
        "evidence_type": "recorded_fixture",
        "evidence_kind": "recorded_fixture",
        "provider_backed": False,
        "human_blind_review": False,
        "ok": bool(verification["ok"]),
        "project_dir": str(project),
        "checks": {
            "prepare_completed": True,
            "single_source_transform_request": True,
            "explicit_style_selection": True,
            "gender_inference_performed": False,
            "transform_verification_present": True,
            "transform_review_gate_rejected_unapproved": True,
            "transform_delta_mean_abs": round(transform_delta, 3),
            "review_proxy_generated": True,
            "review_server_identity": True,
            "range_request_206": True,
            "review_confirmation": True,
            "watch_confirmation": True,
            "render_completed": True,
            "verify_output": verification["ok"],
            "visual_delta_mean_abs": round(visual_delta, 3),
        },
        "limitations": [
            "manual tracking fixture; not MediaPipe provider-backed detection evidence",
            "synthetic 320x180 video; not long-duration or 4K performance evidence",
            "synthetic transformed clip; not provider-backed character or style conversion evidence",
            "no human blind review",
        ],
        "logs": {"proxy_prepare": proxy_prepare.stdout[-500:], "request_prepare": request_prepare.stdout[-500:], "transform_verify": transform_verify.stdout[-800:], "prepare": prepare.stdout[-800:], "watch": watch.stdout[-800:], "render": render.stdout[-800:], "verify": verify.stdout[-800:]},
    }


def main() -> int:
    args = parse_args()
    if args.keep:
        root = args.keep.expanduser().resolve()
        if root.exists() and any(root.iterdir()):
            raise RuntimeError(f"--keep 目录必须为空: {root}")
        root.mkdir(parents=True, exist_ok=True)
        result = execute(root)
    else:
        with tempfile.TemporaryDirectory(prefix="handframe-character-selftest-") as temp:
            root = Path(temp)
            result = execute(root)
    if args.evidence_output:
        root_text = str(root)
        def redact(value):
            if isinstance(value, str):
                return value.replace(root_text, "<fixture_root>")
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            return value
        evidence_payload = redact(result)
        evidence_payload.pop("logs", None)
        evidence_payload["project_dir"] = "<fixture_root>/project"
        evidence = args.evidence_output.expanduser().resolve()
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(evidence_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
