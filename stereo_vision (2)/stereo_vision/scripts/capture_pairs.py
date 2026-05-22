from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereo_pipeline.config import load_config
from stereo_pipeline.io_utils import ensure_dir, open_video_capture, split_combined_stereo_frame


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture synchronized stereo image pairs")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--prefix", default="pair")
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--interval", type=float, help="Seconds between auto captures")
    parser.add_argument("--target-pairs", type=int, help="Number of stereo pairs to save")
    parser.add_argument("--manual", action="store_true", help="Disable timed capture and use SPACE to save")
    return parser.parse_args()


def build_board_settings(config: dict) -> tuple[int, int]:
    board = config["board"]
    return int(board["cols"]), int(board["rows"])


def detect_checkerboard(gray, board_size: tuple[int, int]):
    flags = cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY
    found, corners = cv2.findChessboardCornersSB(gray, board_size, flags=flags)
    if found:
        return True, corners
    legacy_flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    return cv2.findChessboardCorners(gray, board_size, legacy_flags)


def resize_for_detection(image, max_width: int):
    height, width = image.shape[:2]
    if max_width <= 0 or width <= max_width:
        return image, 1.0
    scale = max_width / float(width)
    resized = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
    return resized, scale


def scale_corners(corners, factor: float):
    if corners is None or factor == 1.0:
        return corners
    scaled = corners.copy()
    scaled[:, 0, 0] /= factor
    scaled[:, 0, 1] /= factor
    return scaled


def resize_preview(image, preview_scale: float):
    if preview_scale >= 0.999:
        return image
    height, width = image.shape[:2]
    return cv2.resize(
        image,
        (max(1, int(width * preview_scale)), max(1, int(height * preview_scale))),
        interpolation=cv2.INTER_AREA,
    )


def draw_corners(image, board_size, found, corners):
    preview = image.copy()
    if corners is not None:
        cv2.drawChessboardCorners(preview, board_size, corners, found)
    return preview


def open_captures(runtime: dict):
    source_mode = str(runtime.get("source_mode", "dual")).lower()
    if source_mode == "combined":
        cap = open_video_capture(int(runtime["combined_camera_id"]), runtime)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(runtime["frame_width"]))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(runtime["frame_height"]))
        cap.set(cv2.CAP_PROP_FPS, int(runtime["fps"]))
        return cap, None
    left_cap = open_video_capture(int(runtime["left_camera_id"]), runtime)
    right_cap = open_video_capture(int(runtime["right_camera_id"]), runtime)
    for cap in (left_cap, right_cap):
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(runtime["frame_width"]))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(runtime["frame_height"]))
        cap.set(cv2.CAP_PROP_FPS, int(runtime["fps"]))
    return left_cap, right_cap


def read_stereo_pair(runtime: dict, left_cap, right_cap):
    source_mode = str(runtime.get("source_mode", "dual")).lower()
    if source_mode == "combined":
        ok, combined = left_cap.read()
        if not ok:
            raise RuntimeError("Failed to read from combined stereo device.")
        return split_combined_stereo_frame(combined, str(runtime.get("split_layout", "left_right")))
    ok_left, left_frame = left_cap.read()
    ok_right, right_frame = right_cap.read()
    if not ok_left or not ok_right:
        raise RuntimeError("Failed to read from one or both cameras.")
    return left_frame, right_frame


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    runtime = config["runtime"]
    capture_cfg = config.get("capture", {})
    board_size = build_board_settings(config)
    left_dir = ensure_dir(config["paths"]["calibration_left_dir"])
    right_dir = ensure_dir(config["paths"]["calibration_right_dir"])

    left_cap, right_cap = open_captures(runtime)

    extension = runtime.get("save_extension", "png")
    interval = float(args.interval if args.interval is not None else capture_cfg.get("interval_seconds", 2.0))
    target_pairs = int(args.target_pairs if args.target_pairs is not None else capture_cfg.get("target_pairs", 36))
    detect_before_save = bool(capture_cfg.get("detect_board_before_save", True))
    show_corner_preview = bool(capture_cfg.get("show_corner_preview", True))
    warmup_frames = int(capture_cfg.get("warmup_frames", 15))
    detect_every_n_frames = max(1, int(capture_cfg.get("detect_every_n_frames", 3)))
    detect_max_width = int(capture_cfg.get("detect_max_width", 960))
    preview_scale = float(capture_cfg.get("preview_scale", 0.6))
    settle_before_save_ms = max(0, int(capture_cfg.get("settle_before_save_ms", 200)))
    index = args.start_index
    saved_pairs = 0
    next_capture_ts = time.monotonic() + interval
    frame_counter = 0
    left_found = True
    right_found = True
    left_corners = None
    right_corners = None
    try:
        for _ in range(max(warmup_frames, 0)):
            read_stereo_pair(runtime, left_cap, right_cap)
        while True:
            left_frame, right_frame = read_stereo_pair(runtime, left_cap, right_cap)
            frame_counter += 1
            left_preview = left_frame.copy()
            right_preview = right_frame.copy()
            if (detect_before_save or show_corner_preview) and frame_counter % detect_every_n_frames == 0:
                left_gray = cv2.cvtColor(left_frame, cv2.COLOR_BGR2GRAY)
                right_gray = cv2.cvtColor(right_frame, cv2.COLOR_BGR2GRAY)
                left_small, left_scale = resize_for_detection(left_gray, detect_max_width)
                right_small, right_scale = resize_for_detection(right_gray, detect_max_width)
                left_found, left_corners_small = detect_checkerboard(left_small, board_size)
                right_found, right_corners_small = detect_checkerboard(right_small, board_size)
                left_corners = scale_corners(left_corners_small, left_scale)
                right_corners = scale_corners(right_corners_small, right_scale)
            if show_corner_preview:
                left_preview = draw_corners(left_frame, board_size, left_found, left_corners)
                right_preview = draw_corners(right_frame, board_size, right_found, right_corners)

            preview = cv2.hconcat([
                resize_preview(left_preview, preview_scale),
                resize_preview(right_preview, preview_scale),
            ])
            remaining = max(0.0, next_capture_ts - time.monotonic())
            status = (
                f"saved {saved_pairs}/{target_pairs}  interval {interval:.1f}s  "
                f"board L:{int(left_found)} R:{int(right_found)}"
            )
            mode_text = "manual SPACE save" if args.manual else f"auto in {remaining:.1f}s"
            cv2.putText(
                preview,
                status,
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 255, 0),
                2,
            )
            cv2.putText(
                preview,
                f"{mode_text}  ESC quit",
                (20, 78),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 255, 255),
                2,
            )
            cv2.imshow("stereo_capture", preview)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            should_save = False
            if args.manual and key == 32:
                should_save = True
            elif not args.manual and time.monotonic() >= next_capture_ts:
                should_save = True
                next_capture_ts = time.monotonic() + interval

            if should_save:
                if settle_before_save_ms > 0:
                    cv2.waitKey(settle_before_save_ms)
                    left_frame, right_frame = read_stereo_pair(runtime, left_cap, right_cap)
                    frame_counter += 1
                    if detect_before_save:
                        left_gray = cv2.cvtColor(left_frame, cv2.COLOR_BGR2GRAY)
                        right_gray = cv2.cvtColor(right_frame, cv2.COLOR_BGR2GRAY)
                        left_small, left_scale = resize_for_detection(left_gray, detect_max_width)
                        right_small, right_scale = resize_for_detection(right_gray, detect_max_width)
                        left_found, left_corners_small = detect_checkerboard(left_small, board_size)
                        right_found, right_corners_small = detect_checkerboard(right_small, board_size)
                        left_corners = scale_corners(left_corners_small, left_scale)
                        right_corners = scale_corners(right_corners_small, right_scale)
                if detect_before_save and not (left_found and right_found):
                    print("skip: checkerboard not found in both views")
                    continue
                stem = f"{args.prefix}_{index:04d}"
                left_path = Path(left_dir) / f"{stem}.{extension}"
                right_path = Path(right_dir) / f"{stem}.{extension}"
                cv2.imwrite(str(left_path), left_frame)
                cv2.imwrite(str(right_path), right_frame)
                print(f"saved {left_path.name} and {right_path.name}")
                index += 1
                saved_pairs += 1
                if not args.manual and saved_pairs >= target_pairs:
                    print("target pair count reached")
                    break
    finally:
        left_cap.release()
        if right_cap is not None:
            right_cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
