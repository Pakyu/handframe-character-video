from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common import corners_self_intersect, default_review_config, validate_corners, validate_review_config
from render_video import build_ffmpeg_command, compose, frame_window_open, interpolate_frames, style_selection_at, window_open_at
from review_server import validate_tracking_payload
from prepare_transform_request import build_provider_message, build_request, load_aliases, load_catalog
from prepare_project import imported_tracking, polygon_area, smooth_tracking_segment, stabilize_thin_quad
from verify_output import mean_frame_delta


class ConfigTests(unittest.TestCase):
    def test_default_config_is_valid(self):
        config = default_review_config(5.0, False)
        validated = validate_review_config(config, 5.0, False)
        self.assertEqual(validated["fit_mode"], "clip")
        self.assertFalse(validated["inside_loop"])

    def test_legacy_perspective_config_migrates_to_aligned_clip(self):
        config = default_review_config(5.0, False)
        config["fit_mode"] = "perspective"
        config["inside_loop"] = True
        validated = validate_review_config(config, 5.0, False)
        self.assertEqual(validated["fit_mode"], "clip")
        self.assertFalse(validated["inside_loop"])
        self.assertEqual(validated["audio"]["mode"], "original")

    def test_degenerate_corners_are_rejected_but_self_intersection_is_allowed(self):
        with self.assertRaises(ValueError):
            validate_corners([[0.1, 0.1], [0.3, 0.1], [0.5, 0.1], [0.7, 0.1]])
        crossed = validate_corners([[0.1, 0.1], [0.9, 0.9], [0.9, 0.1], [0.1, 0.9]])
        self.assertEqual(len(crossed), 4)

    def test_bgm_mode_requires_bgm(self):
        config = default_review_config(5.0, False)
        config["audio"]["mode"] = "mix"
        with self.assertRaises(ValueError):
            validate_review_config(config, 5.0, False)

    def test_multi_style_config_requires_each_transform_approval(self):
        config = default_review_config(11.0, False, True, 3)
        config["transform_reviews"] = [
            {"index": 0, "approved": True},
            {"index": 1, "approved": True},
            {"index": 2, "approved": False},
        ]
        validated = validate_review_config(config, 11.0, False, True, 3)
        self.assertFalse(validated["transform_review"]["approved"])
        self.assertEqual(validated["style_sequence"]["order"], [0, 1, 2])
        config["transform_reviews"][2]["approved"] = True
        validated = validate_review_config(config, 11.0, False, True, 3)
        self.assertTrue(validated["transform_review"]["approved"])

    def test_multi_style_default_can_begin_at_open_frame(self):
        config = default_review_config(11.0, False, True, 6, 3.6667)
        self.assertAlmostEqual(config["style_sequence"]["start_seconds"], 3.6667, places=4)
        self.assertAlmostEqual(config["style_sequence"]["segment_seconds"], (11.0 - 3.6667) / 6, places=5)

    def test_multi_style_sequence_rejects_missing_video_index(self):
        config = default_review_config(11.0, False, False, 2)
        config["style_sequence"]["order"] = [0, 2]
        with self.assertRaises(ValueError):
            validate_review_config(config, 11.0, False, False, 2)

    def test_multi_style_sequence_requires_every_video_once(self):
        config = default_review_config(11.0, False, False, 3)
        config["style_sequence"]["order"] = [0, 1, 1]
        with self.assertRaises(ValueError):
            validate_review_config(config, 11.0, False, False, 3)


class TrackingTests(unittest.TestCase):
    def test_imported_tracking_must_match_source_contract(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tracking.json"
            path.write_text(json.dumps({"source_size": [720, 1280], "duration": 11.0, "frames": [{"time": 0.0}], "stats": {"detected_frames": 1}}), encoding="utf-8")
            result = imported_tracking(path, {"width": 720, "height": 1280, "duration": 11.0})
            self.assertEqual(result["detector"]["mode"], "imported-verified")
            with self.assertRaises(ValueError):
                imported_tracking(path, {"width": 1080, "height": 1920, "duration": 11.0})

    def test_interpolation(self):
        frames = [
            {"time": 0.0, "corners": [[0.0, 0.0]] * 4},
            {"time": 2.0, "corners": [[1.0, 1.0]] * 4},
        ]
        actual = interpolate_frames(frames, 1.0)
        self.assertTrue(np.allclose(actual, 0.5))

    def test_web_tracking_payload_is_normalized(self):
        payload = {
            "sample_fps": 6,
            "frames": [
                {
                    "time": 0.0,
                    "corners": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
                    "confidence": 0.8,
                    "source": "detected",
                }
            ],
        }
        result = validate_tracking_payload(payload, 2.0, [320, 180])
        self.assertEqual(result["detector"]["mode"], "automatic-web")
        self.assertEqual(result["stats"]["detection_coverage"], 1.0)
        self.assertTrue(result["frames"][0]["visible"])

    def test_window_opens_as_a_line_before_full_quad(self):
        frames = [
            {"time": 0.0, "corners": [[0.2, 0.2]] * 4, "source": "default"},
            {"time": 0.5, "corners": [[0.2, 0.2]] * 4, "source": "detected", "gesture_phase": "line"},
            {"time": 3.5, "corners": [[0.2, 0.2]] * 4, "source": "detected", "gesture_phase": "opening"},
            {"time": 3.6667, "corners": [[0.2, 0.2]] * 4, "source": "detected", "gesture_phase": "open"},
            {"time": 3.8333, "corners": [[0.2, 0.2]] * 4, "source": "held"},
        ]
        self.assertFalse(window_open_at(frames, 0.0))
        self.assertTrue(window_open_at(frames, 0.5))
        self.assertTrue(window_open_at(frames, 3.5))
        self.assertTrue(window_open_at(frames, 3.6667))
        self.assertTrue(window_open_at(frames, 3.9))
        self.assertFalse(frame_window_open({"source": "detected", "visible": False}))

    def test_degenerate_hand_line_is_stabilized_to_renderable_thin_quad(self):
        candidate = np.array([[0.3, 0.4], [0.7, 0.4], [0.7, 0.4002], [0.3, 0.4002]], dtype=np.float32)
        stabilized = stabilize_thin_quad(candidate)
        self.assertGreaterEqual(polygon_area(stabilized), 0.001)
        self.assertLess(polygon_area(stabilized), 0.005)

    def test_crossed_candidate_preserves_semantic_finger_order(self):
        candidate = np.array([[0.3, 0.3], [0.7, 0.7], [0.7, 0.3], [0.3, 0.7]], dtype=np.float32)
        stabilized = stabilize_thin_quad(candidate)
        self.assertGreater(polygon_area(stabilized), 0.01)
        self.assertTrue(np.allclose(stabilized, candidate))

    def test_crossing_detector_distinguishes_bow_tie_from_convex_quad(self):
        convex = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
        crossed = [[0.1, 0.1], [0.9, 0.9], [0.9, 0.1], [0.1, 0.9]]
        self.assertFalse(corners_self_intersect(convex))
        self.assertTrue(corners_self_intersect(crossed))

    def test_visual_distinctness_proxy_uses_mean_absolute_pixel_delta(self):
        first = np.zeros((8, 8, 3), dtype=np.uint8)
        second = np.full((8, 8, 3), 40, dtype=np.uint8)
        self.assertAlmostEqual(mean_frame_delta(first, second), 40.0)

    def test_local_tracking_smoothing_reduces_reindex_spike(self):
        base = np.array([[0.2, 0.3], [0.8, 0.3], [0.8, 0.7], [0.2, 0.7]], dtype=np.float32)
        frames = []
        for index in range(9):
            quad = base + np.array([index * 0.004, 0.0], dtype=np.float32)
            if index == 4:
                quad = np.roll(quad, -1, axis=0)
                quad[0] += np.array([0.12, -0.08], dtype=np.float32)
            frames.append({"time": index / 6, "corners": quad.tolist(), "source": "detected", "visible": True, "gesture_phase": "open"})
        smoothed = smooth_tracking_segment(frames, 0.2, 1.1, 0.2)
        raw = np.array(frames[4]["corners"])
        fixed = np.array(smoothed[4]["corners"])
        previous = np.array(smoothed[3]["corners"])
        self.assertLess(np.mean(np.linalg.norm(fixed - previous, axis=1)), np.mean(np.linalg.norm(raw - previous, axis=1)))


class FfmpegPlanTests(unittest.TestCase):
    def test_style_sequence_uses_global_time_slots_and_short_crossfade(self):
        sequence = {"enabled": True, "segment_seconds": 1.5, "transition_seconds": 0.12, "order": [0, 1, 2]}
        self.assertEqual(style_selection_at(sequence, 0.5, 3), (0, None, 0.0))
        current, next_index, weight = style_selection_at(sequence, 1.44, 3)
        self.assertEqual((current, next_index), (0, 1))
        self.assertAlmostEqual(weight, 0.5, places=5)
        self.assertEqual(style_selection_at(sequence, 1.5, 3), (1, None, 0.0))
        self.assertEqual(style_selection_at(sequence, 3.0, 3), (2, None, 0.0))
        self.assertEqual(style_selection_at(sequence, 6.0, 3), (2, None, 0.0))

    def test_style_sequence_start_delays_rotation_without_resetting_global_media_time(self):
        sequence = {"enabled": True, "start_seconds": 3.5, "segment_seconds": 1.25, "transition_seconds": 0.1, "order": [0, 1, 2]}
        self.assertEqual(style_selection_at(sequence, 3.49, 3), (0, None, 0.0))
        self.assertEqual(style_selection_at(sequence, 3.5, 3), (0, None, 0.0))
        self.assertEqual(style_selection_at(sequence, 4.75, 3), (1, None, 0.0))

    def test_no_audio_plan_is_explicit(self):
        command, mode = build_ffmpeg_command(
            "ffmpeg",
            Path("video.mp4"),
            Path("source.mp4"),
            None,
            Path("output.mp4"),
            "original",
            0.35,
            False,
            18,
            "medium",
        )
        self.assertEqual(mode, "none")
        self.assertIn("-an", command)

    def test_clip_composition_keeps_overlay_spatially_aligned(self):
        base = np.zeros((100, 100, 3), dtype=np.uint8)
        overlay = np.zeros((100, 100, 3), dtype=np.uint8)
        overlay[40:60, 40:60] = (20, 120, 240)
        corners = np.array([[0.3, 0.3], [0.7, 0.3], [0.7, 0.7], [0.3, 0.7]], dtype=np.float32)
        output = compose(base, overlay, corners, "clip")
        self.assertTrue(np.array_equal(output[50, 50], overlay[50, 50]))
        self.assertTrue(np.array_equal(output[10, 10], base[10, 10]))

    def test_self_intersecting_hand_path_renders_bow_tie_mask_not_convex_hull(self):
        base = np.zeros((200, 200, 3), dtype=np.uint8)
        overlay = np.full((200, 200, 3), 255, dtype=np.uint8)
        crossed = np.array([[0.15, 0.15], [0.85, 0.85], [0.85, 0.15], [0.15, 0.85]], dtype=np.float32)
        output = compose(base, overlay, crossed, "clip")
        filled = output[:, :, 0] > 0
        self.assertLess(int(filled.sum()), 13000)
        self.assertTrue(filled[100, 40])
        self.assertFalse(filled[40, 100])

    def test_perspective_composition_is_rejected(self):
        frame = np.zeros((16, 16, 3), dtype=np.uint8)
        corners = np.array([[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]], dtype=np.float32)
        with self.assertRaises(ValueError):
            compose(frame, frame, corners, "perspective")

    def test_closed_window_returns_source_without_styled_pixels(self):
        base = np.full((32, 32, 3), 15, dtype=np.uint8)
        overlay = np.full((32, 32, 3), 240, dtype=np.uint8)
        corners = np.array([[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]], dtype=np.float32)
        output = compose(base, overlay, corners, "clip", window_open=False)
        self.assertTrue(np.array_equal(output, base))


class ReviewAssetTests(unittest.TestCase):
    def test_portrait_canvas_uses_its_visible_box_for_pointer_coordinates(self):
        review = (Path(__file__).resolve().parents[1] / "assets" / "review.html").read_text(encoding="utf-8")
        self.assertIn("width:auto;height:100%;max-width:100%;max-height:100%", review)
        self.assertNotIn("object-fit:contain;touch-action:none", review)
        self.assertIn("canvas.classList.add('dragging')", review)
        self.assertIn("ev.preventDefault();workingCorners", review)

    def test_review_uses_aligned_mask_window_without_perspective_mapping(self):
        review = (Path(__file__).resolve().parents[1] / "assets" / "review.html").read_text(encoding="utf-8")
        self.assertIn("动态遮罩窗口", review)
        self.assertIn("config.fit_mode='clip'", review)
        self.assertNotIn("四点透视", review)
        self.assertNotIn("function drawTriangle", review)
        self.assertIn("stabilizeQuad", review)
        self.assertNotIn("alignQuadToPrevious", review)
        self.assertIn("gesturePhase=area<.005?'line'", review)
        self.assertIn("visibilityAt(tracking.frames,t)", review)

    def test_review_exposes_multi_style_global_timeline_controls(self):
        review = (Path(__file__).resolve().parents[1] / "assets" / "review.html").read_text(encoding="utf-8")
        self.assertIn("角色轮换", review)
        self.assertIn("每段秒数", review)
        self.assertIn("轮换起点", review)
        self.assertIn("global_timeline:true", review)
        self.assertIn("逐条观看并接受全部 AI 转绘视频", review)
        self.assertIn("浏览器阻止了这次播放", review)
        self.assertIn("source.addEventListener('loadeddata',render)", review)
        self.assertIn("requestedTime=Number(new URLSearchParams(location.search).get('t'))", review)
        self.assertIn("new URLSearchParams(location.search).get('t')", review)


class TransformRequestTests(unittest.TestCase):
    def test_catalog_has_original_and_descriptive_routes(self):
        catalog = load_catalog()
        self.assertIn("original-urban-comic-hero", catalog)
        self.assertIn("original-armored-hero", catalog)
        self.assertIn("warm-handpainted-fantasy-anime", catalog)
        self.assertIn("black-haired-moon-rose-guardian", catalog)
        self.assertFalse(any(item["ip_mode"] == "third-party-character" for item in catalog.values()))
        self.assertEqual(catalog["warm-handpainted-fantasy-anime"]["ip_mode"], "descriptive-style")

    def test_provider_message_records_explicit_selection_without_gender_inference(self):
        style = load_catalog()["original-urban-comic-hero"]
        message = build_provider_message(style)
        self.assertIn("用户明确选择", message)
        self.assertIn("没有根据人物外表推断性别", message)
        self.assertIn("只生成原创角色", message)
        self.assertIn("逐帧全画面对齐", message)

    def test_legacy_named_ip_aliases_resolve_to_original_styles(self):
        aliases = load_aliases()
        self.assertEqual(aliases["marvel-spider-man"], "original-urban-comic-hero")
        self.assertEqual(aliases["marvel-iron-man"], "original-armored-hero")

    def test_provider_instructions_exclude_named_ip_tokens(self):
        messages = " ".join(build_provider_message(style) for style in load_catalog().values()).lower()
        for forbidden in ("蜘蛛侠", "蜘蛛格温", "钢铁侠", "漫威", "spider-man", "iron man", "marvel"):
            self.assertNotIn(forbidden, messages)

    def test_artist_named_request_is_reframed_as_descriptive_style(self):
        style = load_catalog()["warm-handpainted-fantasy-anime"]
        message = build_provider_message(style)
        self.assertNotIn("宫崎骏", message)
        self.assertNotIn("吉卜力", message)
        self.assertIn("手绘奇幻日系动画", message)

    def test_character_replacement_style_changes_identity_but_keeps_motion_anchors(self):
        style = load_catalog()["moon-rose-sorceress"]
        message = build_provider_message(style)
        self.assertIn("脸型、五官气质、发色、发型、妆容、服装与材质应形成明显变化", message)
        self.assertIn("双手与指尖坐标", message)
        self.assertNotIn("头、脸、双手、手指、身体轮廓", message)


class SuccessPlaybookTests(unittest.TestCase):
    def test_public_skill_identity_has_no_author_prefix(self):
        root = Path(__file__).resolve().parents[1]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        interface = (root / "agents" / "interface.yaml").read_text(encoding="utf-8")
        review = (root / "assets" / "review.html").read_text(encoding="utf-8")
        self.assertIn("name: handframe-character-video", skill)
        self.assertIn("手势框角色转绘视频", skill)
        self.assertIn("手势框角色转绘视频", readme)
        self.assertIn("手势框角色转绘视频", interface)
        self.assertIn("手势框角色转绘视频", review)
        former_cn_name = "乔" + "木" + "手势框"
        former_cn_hyphen_name = "乔" + "木" + "-手势框"
        former_machine_name = "qia" + "omu-handframe-video"
        for public_text in (skill, readme, interface, review):
            self.assertNotIn(former_cn_name, public_text)
            self.assertNotIn(former_cn_hyphen_name, public_text)
            self.assertNotIn(former_machine_name, public_text)

    def test_skill_routes_real_production_to_success_playbook(self):
        root = Path(__file__).resolve().parents[1]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        playbook = root / "references" / "production-success-playbook.md"
        self.assertTrue(playbook.exists())
        self.assertIn("references/production-success-playbook.md", skill)

    def test_success_playbook_preserves_verified_production_invariants(self):
        playbook = (
            Path(__file__).resolve().parents[1] / "references" / "production-success-playbook.md"
        ).read_text(encoding="utf-8")
        for invariant in (
            "唯一时间基准",
            "不靠变速凑时长",
            "line → opening → open",
            "fit_mode=clip",
            "不做四点透视",
            "五类时刻",
            "missing evidence",
        ):
            self.assertIn(invariant, playbook)


if __name__ == "__main__":
    unittest.main()
