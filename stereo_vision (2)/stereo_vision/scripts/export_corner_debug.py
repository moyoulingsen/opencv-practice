from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import cv2
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereo_pipeline.calibration import StereoCalibrationPipeline
from stereo_pipeline.config import load_config
from stereo_pipeline.io_utils import ensure_dir, pair_images, read_color_image, read_gray_image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export checkerboard corner debug overlays")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--output-dir", default="data/corner_debug")
    return parser.parse_args()


def write_csv(path: Path, corners) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["index", "x", "y"])
        for index, point in enumerate(corners.reshape(-1, 2)):
            writer.writerow([index, float(point[0]), float(point[1])])


def summarize(corners, image_shape) -> dict:
    pts = corners.reshape(-1, 2)
    min_xy = pts.min(axis=0)
    max_xy = pts.max(axis=0)
    width = float(max_xy[0] - min_xy[0])
    height = float(max_xy[1] - min_xy[1])
    area_ratio = width * height / float(image_shape[1] * image_shape[0])
    return {
        "first_corner": [float(pts[0, 0]), float(pts[0, 1])],
        "last_corner": [float(pts[-1, 0]), float(pts[-1, 1])],
        "bbox": [float(min_xy[0]), float(min_xy[1]), float(max_xy[0]), float(max_xy[1])],
        "board_area_ratio": float(area_ratio),
    }


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    pipeline = StereoCalibrationPipeline(config)
    output_dir = ensure_dir(ROOT / args.output_dir)
    pairs = pair_images(
        config["paths"]["calibration_left_dir"],
        config["paths"]["calibration_right_dir"],
    )

    report: dict[str, dict] = {}
    for left_path, right_path in pairs:
        left_gray = read_gray_image(left_path)
        right_gray = read_gray_image(right_path)
        left_corners = pipeline._detect_corners(left_gray)
        right_corners = pipeline._detect_corners(right_gray)

        pair_report: dict[str, object] = {
            "left_detected": left_corners is not None,
            "right_detected": right_corners is not None,
        }

        if left_corners is not None and right_corners is not None:
            left_corners, right_corners = pipeline._normalize_stereo_corner_order(
                left_corners,
                right_corners,
            )
            left_corners = left_corners.astype("float32")
            right_corners = right_corners.astype("float32")

            left_image = read_color_image(left_path)
            right_image = read_color_image(right_path)
            cv2.drawChessboardCorners(left_image, pipeline.board_size, left_corners, True)
            cv2.drawChessboardCorners(right_image, pipeline.board_size, right_corners, True)

            stem = left_path.stem
            cv2.imwrite(str(output_dir / f"{stem}_left.png"), left_image)
            cv2.imwrite(str(output_dir / f"{stem}_right.png"), right_image)
            write_csv(output_dir / f"{stem}_left.csv", left_corners)
            write_csv(output_dir / f"{stem}_right.csv", right_corners)
            pair_report["left"] = summarize(left_corners, left_gray.shape)
            pair_report["right"] = summarize(right_corners, right_gray.shape)

        report[left_path.stem] = pair_report

    with (output_dir / "corner_report.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(report, handle, sort_keys=False)

    print(f"exported corner debug to {output_dir}")


if __name__ == "__main__":
    main()
