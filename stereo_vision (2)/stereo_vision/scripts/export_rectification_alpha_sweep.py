from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereo_pipeline.config import load_config
from stereo_pipeline.io_utils import ensure_dir, pair_images, read_color_image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export rectification alpha sweep contact sheets")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--stereo-output-dir", default="data/outputs_camera_roll_33_simple_joint")
    parser.add_argument("--output-dir", default="data/rectify_alpha_sweep")
    parser.add_argument("--pair-count", type=int, default=3)
    parser.add_argument("--alpha-step", type=float, default=0.05)
    parser.add_argument("--center-principal-point", action="store_true")
    return parser.parse_args()


def load_stereo_yaml(stereo_output_dir: Path, model: str) -> dict:
    path = stereo_output_dir / f"stereo_{model}.yaml"
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def make_alpha_values(step: float) -> list[float]:
    values: list[float] = []
    current = 0.0
    while current < 1.0 + 1e-9:
        values.append(round(current, 2))
        current += step
    if values[-1] != 1.0:
        values.append(1.0)
    return values


def stack_epilines(left: np.ndarray, right: np.ndarray, step: int = 40) -> np.ndarray:
    canvas = cv2.hconcat([left, right])
    height, width = canvas.shape[:2]
    for y in range(0, height, step):
        cv2.line(canvas, (0, y), (width - 1, y), (0, 255, 255), 1, cv2.LINE_AA)
    return canvas


def rectify_pair(
    left: np.ndarray,
    right: np.ndarray,
    K1: np.ndarray,
    D1: np.ndarray,
    K2: np.ndarray,
    D2: np.ndarray,
    R: np.ndarray,
    T: np.ndarray,
    alpha: float,
    center_principal_point: bool,
) -> tuple[np.ndarray, np.ndarray]:
    image_size = (left.shape[1], left.shape[0])
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
    left_map = cv2.initUndistortRectifyMap(K1, D1, R1, P1, image_size, cv2.CV_32FC1)
    right_map = cv2.initUndistortRectifyMap(K2, D2, R2, P2, image_size, cv2.CV_32FC1)
    left_rectified = cv2.remap(left, left_map[0], left_map[1], cv2.INTER_LINEAR)
    right_rectified = cv2.remap(right, right_map[0], right_map[1], cv2.INTER_LINEAR)
    return left_rectified, right_rectified


def make_tile(image: np.ndarray, alpha: float, tile_width: int = 640) -> np.ndarray:
    height, width = image.shape[:2]
    scale = tile_width / float(width)
    tile = cv2.resize(image, (tile_width, max(1, int(height * scale))), interpolation=cv2.INTER_AREA)
    cv2.rectangle(tile, (0, 0), (190, 32), (0, 0, 0), -1)
    cv2.putText(tile, f"alpha={alpha:.2f}", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return tile


def build_contact_sheet(tiles: list[np.ndarray], title: str, columns: int = 4) -> np.ndarray:
    tile_height = max(tile.shape[0] for tile in tiles)
    tile_width = max(tile.shape[1] for tile in tiles)
    rows = math.ceil(len(tiles) / columns)
    header = np.zeros((60, columns * tile_width, 3), dtype=np.uint8)
    cv2.putText(header, title, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    grid = np.zeros((rows * tile_height, columns * tile_width, 3), dtype=np.uint8)
    for index, tile in enumerate(tiles):
        row = index // columns
        col = index % columns
        y = row * tile_height
        x = col * tile_width
        grid[y : y + tile.shape[0], x : x + tile.shape[1]] = tile
    return cv2.vconcat([header, grid])


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    output_dir = ensure_dir(ROOT / args.output_dir)
    stereo_output_dir = (ROOT / args.stereo_output_dir).resolve()
    stereo = load_stereo_yaml(stereo_output_dir, config["calibration"]["model"])

    K1 = np.asarray(stereo["K1"], dtype=np.float64)
    D1 = np.asarray(stereo["D1"], dtype=np.float64)
    K2 = np.asarray(stereo["K2"], dtype=np.float64)
    D2 = np.asarray(stereo["D2"], dtype=np.float64)
    R = np.asarray(stereo["R"], dtype=np.float64)
    T = np.asarray(stereo["T"], dtype=np.float64)

    pairs = pair_images(config["paths"]["calibration_left_dir"], config["paths"]["calibration_right_dir"])
    alpha_values = make_alpha_values(args.alpha_step)

    for left_path, right_path in pairs[: args.pair_count]:
        left = read_color_image(left_path)
        right = read_color_image(right_path)
        tiles: list[np.ndarray] = []
        for alpha in alpha_values:
            rect_left, rect_right = rectify_pair(
                left,
                right,
                K1,
                D1,
                K2,
                D2,
                R,
                T,
                alpha,
                args.center_principal_point,
            )
            pair_image = stack_epilines(rect_left, rect_right)
            tiles.append(make_tile(pair_image, alpha))
        mode = "centered" if args.center_principal_point else "native"
        title = f"{left_path.stem}  raw size {left.shape[1]}x{left.shape[0]} per eye  {mode}"
        contact_sheet = build_contact_sheet(tiles, title)
        cv2.imwrite(str(output_dir / f"{left_path.stem}_alpha_sweep.png"), contact_sheet)

    print(f"exported alpha sweep to {output_dir}")


if __name__ == "__main__":
    main()
