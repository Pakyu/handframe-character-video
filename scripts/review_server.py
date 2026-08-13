#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from common import (
    SCHEMA_VERSION,
    atomic_write_json,
    file_identity,
    json_sha256,
    read_json,
    utc_now,
    validate_corners,
    validate_review_config,
)


MAX_JSON_BODY = 1_000_000


def validate_tracking_payload(payload: object, duration: float, source_size: list[int]) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("tracking 必须是对象")
    raw_frames = payload.get("frames")
    if not isinstance(raw_frames, list) or not raw_frames or len(raw_frames) > 50000:
        raise ValueError("tracking.frames 数量不合法")
    frames = []
    previous = -1.0
    detected = held = visible_count = 0
    phase_counts = {"line": 0, "opening": 0, "open": 0, "held": 0, "absent": 0}
    for raw in raw_frames:
        if not isinstance(raw, dict):
            raise ValueError("tracking frame 必须是对象")
        time_value = float(raw.get("time", -1))
        if time_value < previous or time_value < 0 or time_value > duration + 0.1:
            raise ValueError("tracking 时间轴不合法")
        previous = time_value
        source_kind = str(raw.get("source", "default"))
        if source_kind not in {"detected", "held", "default"}:
            raise ValueError("tracking source 不合法")
        if source_kind == "detected":
            detected += 1
        if source_kind == "held":
            held += 1
        visible = bool(raw.get("visible", source_kind in {"detected", "held"}))
        gesture_phase = str(raw.get("gesture_phase", "absent" if not visible else "held" if source_kind == "held" else "open"))
        if gesture_phase not in phase_counts:
            raise ValueError("tracking gesture_phase 不合法")
        phase_counts[gesture_phase] += 1
        if visible:
            visible_count += 1
        frames.append(
            {
                "time": round(time_value, 4),
                "corners": validate_corners(raw.get("corners")),
                "confidence": max(0.0, min(1.0, float(raw.get("confidence", 0)))),
                "source": source_kind,
                "visible": visible,
                "gesture_phase": gesture_phase,
            }
        )
    coverage = detected / len(frames)
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "source_size": source_size,
        "duration": duration,
        "sample_fps": max(0.0, min(30.0, float(payload.get("sample_fps", 0)))),
        "detector": {"name": "mediapipe-tasks-vision-web-0.10.14", "mode": "automatic-web"},
        "frames": frames,
        "stats": {
            "sampled_frames": len(frames),
            "detected_frames": detected,
            "held_frames": held,
            "visible_frames": visible_count,
            "phase_counts": phase_counts,
            "detection_coverage": round(coverage, 4),
        },
        "needs_manual_review": coverage < 0.5,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动手势框项目本地审核服务")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--port", type=int, default=8899)
    return parser.parse_args()


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def serve_file(handler: BaseHTTPRequestHandler, path: Path) -> None:
    if not path.is_file():
        handler.send_error(404)
        return
    size = path.stat().st_size
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    range_header = handler.headers.get("Range")
    if range_header and range_header.startswith("bytes="):
        try:
            start_text, end_text = range_header[6:].split("-", 1)
            start = int(start_text) if start_text else 0
            end = int(end_text) if end_text else size - 1
            start = max(0, min(start, size - 1))
            end = max(start, min(end, size - 1))
        except (ValueError, IndexError):
            handler.send_error(416)
            return
        length = end - start + 1
        handler.send_response(206)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(length))
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        handler.send_header("Accept-Ranges", "bytes")
        handler.end_headers()
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 256, remaining))
                if not chunk:
                    break
                handler.wfile.write(chunk)
                remaining -= len(chunk)
        return
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(size))
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 256):
            handler.wfile.write(chunk)


def main() -> int:
    args = parse_args()
    project = args.project_dir.expanduser().resolve()
    manifest_path = project / "manifest.json"
    tracking_path = project / "tracking.json"
    config_path = project / "review_config.json"
    review_path = project / "review.html"
    for required in (manifest_path, tracking_path, config_path, review_path):
        if not required.is_file():
            raise FileNotFoundError(f"项目缺少文件: {required}")
    manifest = read_json(manifest_path)
    source = Path(manifest["source"]["path"])
    inside_metas = manifest.get("insides") or [manifest["inside"]]
    insides = [Path(item["path"]) for item in inside_metas]
    review_media = manifest.get("review_media") or {}
    review_source = Path(review_media.get("source") or source)
    review_inside_values = review_media.get("insides") or [review_media.get("inside") or insides[0]]
    review_insides = [Path(value) for value in review_inside_values]
    bgm = Path(manifest["bgm"]["path"]) if manifest.get("bgm") else None
    for media in (source, *insides, review_source, *review_insides):
        if not media.is_file():
            raise FileNotFoundError(f"媒体文件已移动或删除: {media}")
    if bgm and not bgm.is_file():
        raise FileNotFoundError(f"BGM 文件已移动或删除: {bgm}")
    duration = float(manifest["source"]["duration"])
    origins = manifest.get("inside_origins") or [manifest.get("inside_origin", {})]
    transform_required = any(origin.get("route") == "ai-video-edit" for origin in origins)
    instance_id = secrets.token_hex(12)

    class Handler(BaseHTTPRequestHandler):
        server_version = "HandframeCharacterReview/0.1"

        def log_message(self, fmt: str, *values: object) -> None:
            print(f"[{self.log_date_time_string()}] {fmt % values}")

        def do_GET(self) -> None:
            route = urlparse(self.path).path
            if route in {"/", "/review.html"}:
                serve_file(self, review_path)
                return
            if route == "/api/status":
                send_json(self, 200, read_json(project / "review_server_status.json"))
                return
            if route == "/api/project":
                send_json(
                    self,
                    200,
                    {
                        "manifest": manifest,
                        "tracking": read_json(tracking_path),
                        "config": read_json(config_path),
                        "instance_id": instance_id,
                        "media": {
                            "source": "/media/source",
                            "inside": "/media/inside/0",
                            "insides": [f"/media/inside/{index}" for index in range(len(review_insides))],
                            "bgm": "/media/bgm" if bgm else None,
                        },
                    },
                )
                return
            if route == "/media/source":
                serve_file(self, review_source)
                return
            if route == "/media/inside":
                serve_file(self, review_insides[0]); return
            if route.startswith("/media/inside/"):
                try:
                    index = int(route.rsplit("/", 1)[1])
                    serve_file(self, review_insides[index]); return
                except (ValueError, IndexError):
                    self.send_error(404); return
            if route == "/media/bgm" and bgm:
                serve_file(self, bgm)
                return
            self.send_error(404)

        def do_POST(self) -> None:
            route = urlparse(self.path).path
            if route not in {"/api/save", "/api/confirm", "/api/tracking"}:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_JSON_BODY:
                    raise ValueError("请求体大小不合法")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if payload.get("instance_id") != instance_id:
                    raise ValueError("审核页实例已过期，请刷新页面")
                if route == "/api/tracking":
                    tracking = validate_tracking_payload(
                        payload.get("tracking"),
                        duration,
                        [int(manifest["source"]["width"]), int(manifest["source"]["height"])],
                    )
                    atomic_write_json(tracking_path, tracking)
                    send_json(self, 200, {"ok": True, "tracking": tracking})
                    return
                config = validate_review_config(payload.get("config"), duration, bgm is not None, transform_required, len(insides))
                atomic_write_json(config_path, config)
                if route == "/api/confirm":
                    if transform_required and not config.get("transform_review", {}).get("approved"):
                        raise ValueError("必须先观看并确认 AI 转绘视频的角色、动作和时间稳定性")
                    confirmation = {
                        "schema_version": 1,
                        "confirmed_at": utc_now(),
                        "instance_id": instance_id,
                        "config_sha256": json_sha256(config),
                        "source": file_identity(source),
                        "inside": file_identity(insides[0]),
                        "insides": [file_identity(path) for path in insides],
                        "bgm": file_identity(bgm) if bgm else None,
                    }
                    atomic_write_json(project / "review_confirmed.json", confirmation)
                    send_json(self, 200, {"ok": True, "confirmed": True, "confirmation": confirmation})
                else:
                    send_json(self, 200, {"ok": True, "confirmed": False, "config_sha256": json_sha256(config)})
            except Exception as exc:
                send_json(self, 400, {"ok": False, "error": str(exc)})

    server = None
    selected_port = None
    for port in ([0] if args.port == 0 else range(args.port, args.port + 21)):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            selected_port = int(server.server_address[1])
            break
        except OSError:
            continue
    if server is None or selected_port is None:
        raise RuntimeError("找不到可用审核端口")

    status = {
        "schema_version": 1,
        "pid": os.getpid(),
        "instance_id": instance_id,
        "started_at": utc_now(),
        "port": selected_port,
        "url": f"http://127.0.0.1:{selected_port}/review.html",
        "project_dir": str(project),
        "review_html": str(review_path),
        "source": file_identity(source),
        "inside": file_identity(insides[0]),
        "insides": [file_identity(path) for path in insides],
        "review_source": file_identity(review_source),
        "review_inside": file_identity(review_insides[0]),
        "review_insides": [file_identity(path) for path in review_insides],
        "bgm": file_identity(bgm) if bgm else None,
    }
    atomic_write_json(project / "review_server_status.json", status)
    print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
