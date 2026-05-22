from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereo_pipeline.config import load_config
from stereo_pipeline.depth import StereoDepthPipeline
from stereo_pipeline.io_utils import (
    list_images,
    open_video_capture,
    read_color_image,
    split_combined_stereo_frame,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute stereo disparity and depth")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--source", choices=["live", "files"], default="files")
    parser.add_argument("--save-dir", default="data/outputs/runtime_results")
    return parser.parse_args()


def save_result_images(save_dir: Path, stem: str, result: dict[str, np.ndarray]) -> None:
    save_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(save_dir / f"{stem}_left_rectified.png"), result["left_rectified"])
    cv2.imwrite(str(save_dir / f"{stem}_right_rectified.png"), result["right_rectified"])
    cv2.imwrite(str(save_dir / f"{stem}_left_matched.png"), result["left_matched"])
    cv2.imwrite(str(save_dir / f"{stem}_right_matched.png"), result["right_matched"])
    cv2.imwrite(str(save_dir / f"{stem}_disparity.png"), result["disparity_vis"])
    np.save(save_dir / f"{stem}_depth_m.npy", result["depth_m"])


def run_on_files(config: dict, pipeline: StereoDepthPipeline, save_dir: Path) -> None:
    left_images = list_images(config["paths"]["runtime_left_dir"])
    right_images = list_images(config["paths"]["runtime_right_dir"])
    if len(left_images) != len(right_images):
        raise ValueError("Runtime left/right image count mismatch")
    for left_path, right_path in zip(left_images, right_images, strict=True):
        left = read_color_image(left_path)
        right = read_color_image(right_path)
        result = pipeline.compute(left, right)
        save_result_images(save_dir, left_path.stem, result)
        print(f"processed {left_path.name}")


def run_live(config: dict, pipeline: StereoDepthPipeline, save_dir: Path) -> None:
    runtime = config["runtime"]
    source_mode = str(runtime.get("source_mode", "dual")).lower()
    if source_mode == "combined":
        left_cap = open_video_capture(int(runtime["combined_camera_id"]), runtime)
        right_cap = None
        left_cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(runtime["frame_width"]))
        left_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(runtime["frame_height"]))
        left_cap.set(cv2.CAP_PROP_FPS, int(runtime["fps"]))
    else:
        left_cap = open_video_capture(int(runtime["left_camera_id"]), runtime)
        right_cap = open_video_capture(int(runtime["right_camera_id"]), runtime)
        for cap in (left_cap, right_cap):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(runtime["frame_width"]))
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(runtime["frame_height"]))
            cap.set(cv2.CAP_PROP_FPS, int(runtime["fps"]))
    frame_idx = 1
    try:
        while True:
            if source_mode == "combined":
                ok, combined = left_cap.read()
                if not ok:
                    raise RuntimeError("Failed to read from combined stereo device.")
                left, right = split_combined_stereo_frame(combined, str(runtime.get("split_layout", "left_right")))
            else:
                ok_left, left = left_cap.read()
                ok_right, right = right_cap.read()
                if not ok_left or not ok_right:
                    raise RuntimeError("Failed to read from one or both cameras.")
            result = pipeline.compute(left, right)
            preview = cv2.hconcat([result["left_matched"], result["disparity_vis"]])
            cv2.imshow("stereo_depth", preview)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            if key == ord("s"):
                save_result_images(save_dir, f"live_{frame_idx:04d}", result)
                print(f"saved live_{frame_idx:04d}")
                frame_idx += 1
    finally:
        left_cap.release()
        if right_cap is not None:
            right_cap.release()
        cv2.destroyAllWindows()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    pipeline = StereoDepthPipeline(config)
    save_dir = (ROOT / args.save_dir).resolve()
    if args.source == "files":
        run_on_files(config, pipeline, save_dir)
    else:
        run_live(config, pipeline, save_dir)


if __name__ == "__main__":
    main()
