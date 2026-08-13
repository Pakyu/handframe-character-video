#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from common import atomic_write_json, file_identity, probe_media, utc_now


SKILL_DIR = Path(__file__).resolve().parent.parent
CATALOG_PATH = SKILL_DIR / "assets" / "style-catalog.json"


def load_catalog() -> dict[str, dict[str, Any]]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    styles = data.get("styles") or []
    return {str(item["id"]): item for item in styles}


def load_aliases() -> dict[str, str]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {str(key): str(value) for key, value in (data.get("aliases") or {}).items()}


def build_provider_message(style: dict[str, Any], notes: str = "") -> str:
    if style.get("character_presentation") == "replace-character-preserve-motion-anchor":
        preservation = (
            "角色身份随所选方案完整重塑，脸型、五官气质、发色、发型、妆容、服装与材质应形成明显变化；"
            "只锁定原片的主体数量、动作骨架、身体比例、头部中心、肩线、躯干中心、双手与指尖坐标、动作节奏、镜头、构图、口型时序和场景空间关系；"
            "转绘结果与原片逐帧全画面对齐，保持相同人物占位和背景透视，连续稳定呈现一个原创角色。"
        )
    else:
        preservation = (
            "保持原片的主体数量、人物体态、动作节奏、镜头运动、构图、口型时序和场景空间关系；"
            "转绘结果必须与原片逐帧全画面对齐，头、脸、双手、手指、身体轮廓和背景结构保持同一画面坐标，不得重新取景、缩放主体或改变透视；"
            "不要新增或删除人物，不改变手势动作，不出现肢体增生、脸部漂移、闪烁、文字、字幕、品牌字样或水印。"
        )
    selection = "角色或画面风格由用户明确选择；没有根据人物外表推断性别、性别身份或其他敏感属性。"
    originality = "只生成原创角色或描述性画风；不要出现、提及或复刻任何现有影视、漫画、游戏角色及其名称、标志、经典配色或精确设计。"
    user_notes = f" 用户补充要求：{notes.strip()}" if notes.strip() else ""
    return " ".join(part for part in [style["provider_instruction"], preservation, selection, originality, user_notes] if part)


def build_request(source: Path, style_id: str, usage: str, notes: str = "") -> dict[str, Any]:
    catalog = load_catalog()
    aliases = load_aliases()
    requested_style_id = style_id
    style_id = aliases.get(style_id, style_id)
    if style_id not in catalog:
        raise ValueError(f"未知 style-id: {requested_style_id}；可选原创/描述性值: {', '.join(sorted(catalog))}")
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"原始视频不存在: {source}")
    style = catalog[style_id]
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "source": probe_media(source),
        "source_identity": file_identity(source),
        "selection": {
            "style_id": style_id,
            "requested_style_id": requested_style_id,
            "display_name": style["display_name"],
            "category": style["category"],
            "character_presentation": style["character_presentation"],
            "selection_source": "user-explicit",
            "gender_inference_performed": False,
            "sensitive_attribute_inference_performed": False,
            "ip_reframing_performed": requested_style_id != style_id,
        },
        "ip": {
            "mode": style["ip_mode"],
            "fallback_style_id": None,
            "usage_context": usage,
            "commercial_rights_unverified": False,
        },
        "provider": {
            "preferred_adapter": "xyq-backend-agent",
            "submission_requires_user_credit_confirmation": True,
            "media_upload_requires_user_confirmation": True,
            "message": build_provider_message(style, notes),
        },
        "human_gates": {
            "style_selection_confirmed": True,
            "external_submission_confirmed": False,
            "generated_video_reviewed": False,
        },
        "limitations": [
            "未执行或尝试根据外表判断人物性别。",
            "自动媒体检查不能证明角色准确性、动作连贯性或商业使用权。",
            "现有 IP 或命名画风请求只作为本地路由信号，不会进入 Provider 提示词。",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从单条原片创建人物/画面风格视频转绘请求")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--style-id", required=True, help="必须由用户明确选择；不从人物外表推断")
    parser.add_argument("--usage", choices=("personal", "commercial", "unspecified"), default="unspecified")
    parser.add_argument("--notes", default="", help="用户明确补充的要求，原样追加")
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output_dir.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"输出目录不是空目录: {output}")
    output.mkdir(parents=True, exist_ok=True)
    request = build_request(args.source, args.style_id, args.usage, args.notes)
    request_path = output / "transformation_request.json"
    message_path = output / "provider_message.txt"
    atomic_write_json(request_path, request)
    message_path.write_text(request["provider"]["message"] + "\n", encoding="utf-8")
    print(json.dumps({"request": str(request_path), "provider_message": str(message_path), "style_id": args.style_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
