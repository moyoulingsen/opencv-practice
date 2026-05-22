from __future__ import annotations

import argparse
import time
from pathlib import Path
import sys

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereo_pipeline.config import load_config
from stereo_pipeline.io_utils import (
    ensure_dir,
    open_video_capture,
    read_color_image,
    split_combined_stereo_frame,
)
from stereo_pipeline.preprocess import balance_pair_brightness


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live stereo rectification")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--stereo-dir", default="data/outputs_camera_roll_33_simple_joint")
    parser.add_argument("--alpha", type=float, default=0.20)
    parser.add_argument("--save-dir", default="data/runtime_rectified_captures")
    parser.add_argument(
        "--view",
        choices=["rectified_pair", "compare", "left", "right"],
        default="rectified_pair",
    )
    parser.add_argument("--native-principal-point", action="store_true")
    parser.add_argument("--no-balance", action="store_true")
    parser.add_argument("--left-file")
    parser.add_argument("--right-file")
    return parser.parse_args()


def load_stereo_params(stereo_dir: Path, model: str) -> dict:
    path = stereo_dir / f"stereo_{model}.yaml"
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def build_maps(
    stereo: dict,
    image_size: tuple[int, int],
    alpha: float,
    center_principal_point: bool,
) -> tuple[tuple[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]:
    K1 = np.asarray(stereo["K1"], dtype=np.float64)
    D1 = np.asarray(stereo["D1"], dtype=np.float64)
    K2 = np.asarray(stereo["K2"], dtype=np.float64)
    D2 = np.asarray(stereo["D2"], dtype=np.float64)
    R = np.asarray(stereo["R"], dtype=np.float64)
    T = np.asarray(stereo["T"], dtype=np.float64)

    R1, R2, P1, P2, _, _, _ = cv2.stereoRectify(
        K1,
        D1,
        K2,
        D2,
        image_size,
        R,
        T,
        alpha=alpha,
    )

    if center_principal_point:
        shift_x = image_size[0] / 2.0 - float(P1[0, 2])
        shift_y = image_size[1] / 2.0 - float(P1[1, 2])
        P1 = P1.copy()
        P2 = P2.copy()
        P1[0, 2] += shift_x
        P2[0, 2] += shift_x
        P1[1, 2] += shift_y
        P2[1, 2] += shift_y

    left_maps = cv2.initUndistortRectifyMap(K1, D1, R1, P1, image_size, cv2.CV_32FC1)
    right_maps = cv2.initUndistortRectifyMap(K2, D2, R2, P2, image_size, cv2.CV_32FC1)
    return left_maps, right_maps


def rectify(left: np.ndarray, right: np.ndarray, maps) -> tuple[np.ndarray, np.ndarray]:
    left_maps, right_maps = maps
    left_rectified = cv2.remap(left, left_maps[0], left_maps[1], cv2.INTER_LINEAR)
    right_rectified = cv2.remap(right, right_maps[0], right_maps[1], cv2.INTER_LINEAR)
    return left_rectified, right_rectified


def draw_epilines(pair_image: np.ndarray, step: int = 40) -> np.ndarray:
    canvas = pair_image.copy()
    for y in range(0, canvas.shape[0], step):
        cv2.line(canvas, (0, y), (canvas.shape[1] - 1, y), (0, 255, 255), 1, cv2.LINE_AA)
    return canvas


def make_preview(view: str, left: np.ndarray, right: np.ndarray, left_rect: np.ndarray, right_rect: np.ndarray) -> np.ndarray:
    rect_pair = draw_epilines(cv2.hconcat([left_rect, right_rect]))
    if view == "rectified_pair":
        return rect_pair
    if view == "left":
        return left_rect
    if view == "right":
        return right_rect
    raw_pair = draw_epilines(cv2.hconcat([left, right]))
    width = max(raw_pair.shape[1], rect_pair.shape[1])
    if raw_pair.shape[1] != width:
        raw_pair = cv2.copyMakeBorder(raw_pair, 0, 0, 0, width - raw_pair.shape[1], cv2.BORDER_CONSTANT)
    if rect_pair.shape[1] != width:
        rect_pair = cv2.copyMakeBorder(rect_pair, 0, 0, 0, width - rect_pair.shape[1], cv2.BORDER_CONSTANT)
    return cv2.vconcat([raw_pair, rect_pair])


def save_outputs(save_dir: Path, stem: str, left_rect: np.ndarray, right_rect: np.ndarray) -> None:
    save_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(save_dir / f"{stem}_left_rectified.png"), left_rect)
    cv2.imwrite(str(save_dir / f"{stem}_right_rectified.png"), right_rect)
    cv2.imwrite(str(save_dir / f"{stem}_pair_rectified.png"), cv2.hconcat([left_rect, right_rect]))


def run_file_mode(args: argparse.Namespace, maps, config: dict) -> None:
    if not args.left_file or not args.right_file:
        raise ValueError("File mode requires both --left-file and --right-file.")
    left = read_color_image(args.left_file)
    right = read_color_image(args.right_file)
    left_rect, right_rect = rectify(left, right, maps)
    if not args.no_balance:
        left_rect, right_rect = balance_pair_brightness(
            left_rect,
            right_rect,
            config.get("preprocessing", {}).get("brightness_balance", {}),
        )
    save_dir = ensure_dir(ROOT / args.save_dir)
    save_outputs(save_dir, "file_mode", left_rect, right_rect)
    print(f"saved rectified images to {save_dir}")


def open_captures(runtime: dict):
    source_mode = str(runtime.get("source_mode", "combined")).lower()
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


def read_stereo_pair(runtime: dict, left_cap, right_cap) -> tuple[np.ndarray, np.ndarray]:
    source_mode = str(runtime.get("source_mode", "combined")).lower()
    if source_mode == "combined":
        ok, combined = left_cap.read()
        if not ok:
            raise RuntimeError("Failed to read combined stereo frame.")
        return split_combined_stereo_frame(combined, str(runtime.get("split_layout", "left_right")))
    ok_left, left = left_cap.read()
    ok_right, right = right_cap.read()
    if not ok_left or not ok_right:
        raise RuntimeError("Failed to read from stereo cameras.")
    return left, right


def run_live_mode(args: argparse.Namespace, config: dict, maps) -> None:
    runtime = config["runtime"]
    left_cap, right_cap = open_captures(runtime)
    save_dir = ensure_dir(ROOT / args.save_dir)
    frame_index = 1
    last_tick = time.perf_counter()
    fps = 0.0
    try:
        while True:
            left, right = read_stereo_pair(runtime, left_cap, right_cap)
            left_rect, right_rect = rectify(left, right, maps)
            if not args.no_balance:
                left_rect, right_rect = balance_pair_brightness(
                    left_rect,
                    right_rect,
                    config.get("preprocessing", {}).get("brightness_balance", {}),
                )
            preview = make_preview(args.view, left, right, left_rect, right_rect)
            now = time.perf_counter()
            delta = max(now - last_tick, 1e-6)
            fps = 0.9 * fps + 0.1 * (1.0 / delta) if fps > 0 else 1.0 / delta
            last_tick = now
            cv2.putText(
                preview,
                f"alpha={args.alpha:.2f}  centered={not args.native_principal_point}  balance={not args.no_balance}  fps={fps:.1f}  s=save  esc=quit",
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow("rectified_live", preview)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            if key == ord("s"):
                stem = f"live_{frame_index:04d}"
                save_outputs(save_dir, stem, left_rect, right_rect)
                print(f"saved {stem} to {save_dir}")
                frame_index += 1
    finally:
        left_cap.release()
        if right_cap is not None:
            right_cap.release()
        cv2.destroyAllWindows()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    stereo_dir = (ROOT / args.stereo_dir).resolve()
    stereo = load_stereo_params(stereo_dir, config["calibration"]["model"])
    image_size = (int(stereo["image_width"]), int(stereo["image_height"]))
    maps = build_maps(
        stereo,
        image_size,
        args.alpha,
        center_principal_point=not args.native_principal_point,
    )

    if args.left_file or args.right_file:
        run_file_mode(args, maps, config)
    else:
        run_live_mode(args, config, maps)


if __name__ == "__main__":
    main()
