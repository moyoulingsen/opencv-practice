from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereo_pipeline.config import load_config
from stereo_pipeline.depth import StereoDepthPipeline
from stereo_pipeline.io_utils import read_color_image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure depth statistics in an ROI")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--left", required=True)
    parser.add_argument("--right", required=True)
    parser.add_argument("--roi", nargs=4, type=int, metavar=("X", "Y", "W", "H"), required=True)
    parser.add_argument("--expected-distance-m", type=float)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    pipeline = StereoDepthPipeline(config)
    left = read_color_image(args.left)
    right = read_color_image(args.right)
    result = pipeline.compute(left, right)
    x, y, w, h = args.roi
    roi = result["depth_m"][y : y + h, x : x + w]
    valid = roi[np.isfinite(roi)]
    if valid.size == 0:
        raise ValueError("No valid depth samples inside ROI")
    median = float(np.median(valid))
    mean = float(np.mean(valid))
    std = float(np.std(valid))
    print(f"roi_sample_count: {valid.size}")
    print(f"roi_depth_mean_m: {mean:.6f}")
    print(f"roi_depth_median_m: {median:.6f}")
    print(f"roi_depth_std_m: {std:.6f}")
    if args.expected_distance_m is not None:
        abs_error = abs(mean - args.expected_distance_m)
        rel_error = abs_error / args.expected_distance_m if args.expected_distance_m > 0 else float("nan")
        print(f"expected_distance_m: {args.expected_distance_m:.6f}")
        print(f"absolute_error_m: {abs_error:.6f}")
        print(f"relative_error: {rel_error:.6%}")


if __name__ == "__main__":
    main()
