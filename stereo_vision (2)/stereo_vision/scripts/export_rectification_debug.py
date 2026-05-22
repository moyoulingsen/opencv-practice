from __future__ import annotations

import argparse
from pathlib import Path
import sys

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereo_pipeline.calibration import StereoCalibrationPipeline
from stereo_pipeline.config import load_config
from stereo_pipeline.io_utils import ensure_dir, pair_images, read_color_image, read_gray_image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export rectification debug images and metrics")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--output-dir", default="data/rectify_debug")
    return parser.parse_args()


def load_stereo_params(output_dir: Path, model: str) -> dict:
    path = output_dir / f"stereo_{model}.yaml"
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def draw_points(image: np.ndarray, corners: np.ndarray, color: tuple[int, int, int]) -> np.ndarray:
    canvas = image.copy()
    points = corners.reshape(-1, 2)
    for index, point in enumerate(points):
        x = int(round(float(point[0])))
        y = int(round(float(point[1])))
        cv2.circle(canvas, (x, y), 4, color, -1)
        cv2.putText(canvas, str(index), (x + 4, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)
    return canvas


def stack_with_epilines(left: np.ndarray, right: np.ndarray, step: int = 60) -> np.ndarray:
    canvas = cv2.hconcat([left, right])
    height, width = canvas.shape[:2]
    for y in range(0, height, step):
        cv2.line(canvas, (0, y), (width - 1, y), (0, 255, 255), 1, cv2.LINE_AA)
    return canvas


def summarize_pair(raw_left: np.ndarray, raw_right: np.ndarray, rect_left: np.ndarray, rect_right: np.ndarray) -> dict:
    raw_left_pts = raw_left.reshape(-1, 2)
    raw_right_pts = raw_right.reshape(-1, 2)
    rect_left_pts = rect_left.reshape(-1, 2)
    rect_right_pts = rect_right.reshape(-1, 2)
    raw_vertical = raw_left_pts[:, 1] - raw_right_pts[:, 1]
    rect_vertical = rect_left_pts[:, 1] - rect_right_pts[:, 1]
    raw_disparity = raw_left_pts[:, 0] - raw_right_pts[:, 0]
    rect_disparity = rect_left_pts[:, 0] - rect_right_pts[:, 0]
    return {
        "raw_vertical_mae_px": float(np.mean(np.abs(raw_vertical))),
        "raw_vertical_std_px": float(np.std(raw_vertical)),
        "rectified_vertical_mae_px": float(np.mean(np.abs(rect_vertical))),
        "rectified_vertical_std_px": float(np.std(rect_vertical)),
        "raw_mean_disparity_px": float(np.mean(raw_disparity)),
        "rectified_mean_disparity_px": float(np.mean(rect_disparity)),
    }


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    pipeline = StereoCalibrationPipeline(config)
    output_dir = ensure_dir(ROOT / args.output_dir)
    stereo_output_dir = Path(config["paths"]["output_dir"])
    stereo = load_stereo_params(stereo_output_dir, config["calibration"]["model"])
    rect_maps = np.load(stereo_output_dir / "rectification_maps.npz")

    K1 = np.asarray(stereo["K1"], dtype=np.float64)
    D1 = np.asarray(stereo["D1"], dtype=np.float64).reshape(-1, 1)
    K2 = np.asarray(stereo["K2"], dtype=np.float64)
    D2 = np.asarray(stereo["D2"], dtype=np.float64).reshape(-1, 1)
    R1 = np.asarray(stereo["R1"], dtype=np.float64)
    R2 = np.asarray(stereo["R2"], dtype=np.float64)
    P1 = np.asarray(stereo["P1"], dtype=np.float64)
    P2 = np.asarray(stereo["P2"], dtype=np.float64)

    report: dict[str, dict] = {}
    pairs = pair_images(
        config["paths"]["calibration_left_dir"],
        config["paths"]["calibration_right_dir"],
    )

    aggregate = {
        "raw_vertical_mae_px": [],
        "rectified_vertical_mae_px": [],
    }

    for left_path, right_path in pairs:
        left_gray = read_gray_image(left_path)
        right_gray = read_gray_image(right_path)
        left_corners = pipeline._detect_corners(left_gray)
        right_corners = pipeline._detect_corners(right_gray)
        if left_corners is None or right_corners is None:
            report[left_path.stem] = {"left_detected": left_corners is not None, "right_detected": right_corners is not None}
            continue

        left_corners, right_corners = pipeline._normalize_stereo_corner_order(left_corners, right_corners)
        rect_left_pts = cv2.undistortPoints(left_corners.astype(np.float64), K1, D1, R=R1, P=P1)
        rect_right_pts = cv2.undistortPoints(right_corners.astype(np.float64), K2, D2, R=R2, P=P2)

        metrics = summarize_pair(left_corners, right_corners, rect_left_pts, rect_right_pts)
        aggregate["raw_vertical_mae_px"].append(metrics["raw_vertical_mae_px"])
        aggregate["rectified_vertical_mae_px"].append(metrics["rectified_vertical_mae_px"])
        report[left_path.stem] = metrics

        left_color = read_color_image(left_path)
        right_color = read_color_image(right_path)
        left_raw_vis = draw_points(left_color, left_corners.astype(np.float32), (0, 255, 0))
        right_raw_vis = draw_points(right_color, right_corners.astype(np.float32), (0, 255, 0))

        rect_left_img = cv2.remap(
            left_color,
            rect_maps["left_map_x"],
            rect_maps["left_map_y"],
            cv2.INTER_LINEAR,
        )
        rect_right_img = cv2.remap(
            right_color,
            rect_maps["right_map_x"],
            rect_maps["right_map_y"],
            cv2.INTER_LINEAR,
        )
        rect_left_vis = draw_points(rect_left_img, rect_left_pts.astype(np.float32), (0, 255, 0))
        rect_right_vis = draw_points(rect_right_img, rect_right_pts.astype(np.float32), (0, 255, 0))

        stem = left_path.stem
        cv2.imwrite(str(output_dir / f"{stem}_raw_pair.png"), stack_with_epilines(left_raw_vis, right_raw_vis))
        cv2.imwrite(str(output_dir / f"{stem}_rectified_pair.png"), stack_with_epilines(rect_left_vis, rect_right_vis))

    report["summary"] = {
        "pair_count": len(aggregate["raw_vertical_mae_px"]),
        "raw_vertical_mae_mean_px": float(np.mean(aggregate["raw_vertical_mae_px"])) if aggregate["raw_vertical_mae_px"] else 0.0,
        "rectified_vertical_mae_mean_px": float(np.mean(aggregate["rectified_vertical_mae_px"])) if aggregate["rectified_vertical_mae_px"] else 0.0,
        "raw_vertical_mae_max_px": float(np.max(aggregate["raw_vertical_mae_px"])) if aggregate["raw_vertical_mae_px"] else 0.0,
        "rectified_vertical_mae_max_px": float(np.max(aggregate["rectified_vertical_mae_px"])) if aggregate["rectified_vertical_mae_px"] else 0.0,
    }

    with (output_dir / "rectification_report.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(report, handle, sort_keys=False)

    print(f"exported rectification debug to {output_dir}")


if __name__ == "__main__":
    main()
