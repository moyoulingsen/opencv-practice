#!/usr/bin/env python3
"""Calibrate the MF287/TB2 side-by-side USB stereo camera.

The camera appears as a UVC/V4L2 device that outputs one frame containing
left and right images. This tool captures chessboard pairs and produces a
calibration file used by mf287_depth_camera.py to generate metric depth maps.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np


CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MF287 stereo calibration utility.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    board = subparsers.add_parser("make-board", help="Create a printable chessboard SVG.")
    board.add_argument("--pattern-cols", type=int, default=9, help="Inner corner columns.")
    board.add_argument("--pattern-rows", type=int, default=6, help="Inner corner rows.")
    board.add_argument("--square-size", type=float, default=25.0, help="Square size in millimeters.")
    board.add_argument("--output", default="mf287_chessboard_9x6_25mm.svg", help="Output SVG path.")

    capture = subparsers.add_parser("capture", help="Capture synchronized chessboard image pairs.")
    add_camera_args(capture)
    add_pattern_args(capture)
    capture.add_argument("--output-dir", default="mf287_calibration_images", help="Directory for captured pairs.")
    capture.add_argument("--save-any", action="store_true", help="Allow saving when corners are not detected.")

    calibrate = subparsers.add_parser("calibrate", help="Create mf287_calib.npz from captured pairs.")
    add_pattern_args(calibrate)
    calibrate.add_argument("--image-dir", default="mf287_calibration_images", help="Directory containing pairs.")
    calibrate.add_argument("--output", default="mf287_calib.npz", help="Output calibration file.")
    calibrate.add_argument("--min-pairs", type=int, default=15, help="Minimum valid image pairs.")
    calibrate.add_argument("--alpha", type=float, default=0.0, help="stereoRectify alpha, 0 crops, 1 keeps all.")
    calibrate.add_argument("--debug-dir", default="", help="Optional directory for rectified debug images.")
    calibrate.add_argument(
        "--fix-intrinsic",
        action="store_true",
        help="Keep individual camera intrinsics fixed during stereo calibration.",
    )

    return parser.parse_args()


def add_camera_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--device", type=int, default=4, help="Video index, e.g. 4 for /dev/video4.")
    parser.add_argument("--width", type=int, default=2560, help="Full side-by-side capture width.")
    parser.add_argument("--height", type=int, default=720, help="Full side-by-side capture height.")
    parser.add_argument("--fps", type=int, default=30, help="Requested FPS.")
    parser.add_argument("--swap", action="store_true", help="Swap left/right images.")
    parser.add_argument("--manual-controls", action="store_true", help="Do not reset UVC exposure/white-balance controls.")
    parser.add_argument("--exposure", type=int, default=-1, help="Manual exposure value. -1 keeps auto exposure.")
    parser.add_argument("--gain", type=int, default=0, help="Manual gain value used with --exposure.")


def add_pattern_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pattern-cols", type=int, default=9, help="Chessboard inner corner columns.")
    parser.add_argument("--pattern-rows", type=int, default=6, help="Chessboard inner corner rows.")
    parser.add_argument("--square-size", type=float, default=25.0, help="Real square size in millimeters.")


def make_board(args: argparse.Namespace) -> int:
    squares_x = args.pattern_cols + 1
    squares_y = args.pattern_rows + 1
    width_mm = squares_x * args.square_size
    height_mm = squares_y * args.square_size
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm}mm" '
            f'height="{height_mm}mm" viewBox="0 0 {width_mm} {height_mm}">'
        ),
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for row in range(squares_y):
        for col in range(squares_x):
            if (row + col) % 2 == 0:
                x = col * args.square_size
                y = row * args.square_size
                parts.append(
                    f'<rect x="{x}" y="{y}" width="{args.square_size}" '
                    f'height="{args.square_size}" fill="black"/>'
                )
    parts.append("</svg>")
    output = Path(args.output)
    output.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    print("Print it at 100% scale.")
    print(f"OpenCV inner corners: {args.pattern_cols}x{args.pattern_rows}")
    print(f"Square size: {args.square_size} mm")
    return 0


def open_camera(args: argparse.Namespace) -> cv2.VideoCapture:
    configure_uvc_controls(args)
    cap = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open /dev/video{args.device}.")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, args.fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not args.manual_controls:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
        cap.set(cv2.CAP_PROP_AUTO_WB, 1)
    return cap


def configure_uvc_controls(args: argparse.Namespace) -> None:
    if args.manual_controls:
        return

    device = f"/dev/video{args.device}"
    if args.exposure >= 0:
        controls = {
            "auto_exposure": 1,
            "exposure_time_absolute": args.exposure,
            "gain": args.gain,
            "white_balance_automatic": 1,
            "backlight_compensation": 0,
        }
    else:
        controls = {
            "auto_exposure": 3,
            "white_balance_automatic": 1,
            "backlight_compensation": 0,
        }

    cmd = ["v4l2-ctl", "-d", device, "--set-ctrl=" + ",".join(f"{key}={value}" for key, value in controls.items())]
    try:
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass


def split_side_by_side(frame: np.ndarray, swap: bool = False) -> tuple[np.ndarray, np.ndarray]:
    mid = frame.shape[1] // 2
    left = frame[:, :mid]
    right = frame[:, mid:]
    if swap:
        return right, left
    return left, right


def chessboard_flags() -> int:
    flags = cv2.CALIB_CB_NORMALIZE_IMAGE
    if hasattr(cv2, "CALIB_CB_EXHAUSTIVE"):
        flags |= cv2.CALIB_CB_EXHAUSTIVE
    return flags


def find_chessboard(image: np.ndarray, pattern_size: tuple[int, int]) -> tuple[bool, np.ndarray | None]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if hasattr(cv2, "findChessboardCornersSB"):
        ok, corners = cv2.findChessboardCornersSB(gray, pattern_size, flags=chessboard_flags())
        if ok:
            return True, corners.astype(np.float32)

    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    ok, corners = cv2.findChessboardCorners(gray, pattern_size, flags=flags)
    if not ok:
        return False, None
    corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), CRITERIA)
    return True, corners.astype(np.float32)


def corner_order_variants(corners: np.ndarray, pattern_size: tuple[int, int]) -> list[tuple[str, np.ndarray]]:
    cols, rows = pattern_size
    grid = corners.reshape(rows, cols, 1, 2)
    variants = [
        ("normal", grid),
        ("flip_cols", grid[:, ::-1]),
        ("flip_rows", grid[::-1, :]),
        ("rot180", grid[::-1, ::-1]),
    ]
    return [(name, variant.reshape(-1, 1, 2).astype(np.float32)) for name, variant in variants]


def align_right_corners(
    left_corners: np.ndarray,
    right_corners: np.ndarray,
    pattern_size: tuple[int, int],
) -> tuple[np.ndarray, str, float]:
    best_name = "normal"
    best_corners = right_corners
    best_error = float("inf")
    left_points = left_corners.reshape(-1, 2)
    for name, candidate in corner_order_variants(right_corners, pattern_size):
        right_points = candidate.reshape(-1, 2)
        # The raw stereo pair is close to horizontally aligned, so corresponding
        # physical corners should have similar y coordinates before calibration.
        error = float(np.median(np.abs(left_points[:, 1] - right_points[:, 1])))
        if error < best_error:
            best_name = name
            best_corners = candidate
            best_error = error
    return best_corners, best_name, best_error


def next_pair_index(output_dir: Path) -> int:
    max_index = -1
    for path in output_dir.glob("pair_*_left.*"):
        match = re.match(r"pair_(\d+)_left\.", path.name)
        if match:
            max_index = max(max_index, int(match.group(1)))
    return max_index + 1


def draw_capture_preview(
    left: np.ndarray,
    right: np.ndarray,
    left_ok: bool,
    left_corners: np.ndarray | None,
    right_ok: bool,
    right_corners: np.ndarray | None,
    pattern_size: tuple[int, int],
    saved_count: int,
) -> np.ndarray:
    left_view = left.copy()
    right_view = right.copy()
    if left_corners is not None:
        cv2.drawChessboardCorners(left_view, pattern_size, left_corners, left_ok)
    if right_corners is not None:
        cv2.drawChessboardCorners(right_view, pattern_size, right_corners, right_ok)

    preview_left = cv2.resize(left_view, (640, 360), interpolation=cv2.INTER_AREA)
    preview_right = cv2.resize(right_view, (640, 360), interpolation=cv2.INTER_AREA)
    preview = np.hstack((preview_left, preview_right))
    left_brightness = float(cv2.cvtColor(left, cv2.COLOR_BGR2GRAY).mean())
    right_brightness = float(cv2.cvtColor(right, cv2.COLOR_BGR2GRAY).mean())
    color = (0, 180, 0) if left_ok and right_ok else (0, 0, 255)
    status = "READY" if left_ok and right_ok else "NO BOARD"
    cv2.rectangle(preview, (8, 8), (820, 104), (0, 0, 0), -1)
    cv2.putText(preview, status, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA)
    cv2.putText(
        preview,
        f"s save | q/ESC quit | saved {saved_count}",
        (20, 66),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (235, 235, 235),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        preview,
        f"left brightness {left_brightness:5.1f} | right brightness {right_brightness:5.1f}",
        (20, 92),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (230, 230, 230),
        1,
        cv2.LINE_AA,
    )
    return preview


def capture_pairs(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern_size = (args.pattern_cols, args.pattern_rows)
    pair_index = next_pair_index(output_dir)
    saved_count = 0

    cap = open_camera(args)
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                print("No frame received.")
                time.sleep(0.1)
                continue

            left, right = split_side_by_side(frame, args.swap)
            left_ok, left_corners = find_chessboard(left, pattern_size)
            right_ok, right_corners = find_chessboard(right, pattern_size)
            preview = draw_capture_preview(
                left,
                right,
                left_ok,
                left_corners,
                right_ok,
                right_corners,
                pattern_size,
                saved_count,
            )
            cv2.imshow("MF287 calibration capture", preview)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            if key == ord("s"):
                if not args.save_any and not (left_ok and right_ok):
                    print("Not saved: chessboard must be detected in both images.")
                    continue
                left_path = output_dir / f"pair_{pair_index:04d}_left.jpg"
                right_path = output_dir / f"pair_{pair_index:04d}_right.jpg"
                full_path = output_dir / f"pair_{pair_index:04d}_full.jpg"
                cv2.imwrite(str(left_path), left)
                cv2.imwrite(str(right_path), right)
                cv2.imwrite(str(full_path), frame)
                print(f"Saved pair {pair_index:04d}: {left_path.name}, {right_path.name}")
                pair_index += 1
                saved_count += 1
    finally:
        cap.release()
        cv2.destroyAllWindows()

    return 0


def list_image_pairs(image_dir: Path) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    candidates = sorted(image_dir.glob("pair_*_left.*"))
    for left_path in candidates:
        right_path = left_path.with_name(left_path.name.replace("_left.", "_right."))
        if right_path.exists():
            pairs.append((left_path, right_path))
    return pairs


def make_object_points(pattern_size: tuple[int, int], square_size: float) -> np.ndarray:
    cols, rows = pattern_size
    objp = np.zeros((cols * rows, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp *= square_size
    return objp


def reprojection_error(
    object_points: list[np.ndarray],
    image_points: list[np.ndarray],
    rvecs: tuple[np.ndarray, ...],
    tvecs: tuple[np.ndarray, ...],
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
) -> float:
    total_error = 0.0
    total_points = 0
    for objp, imgp, rvec, tvec in zip(object_points, image_points, rvecs, tvecs):
        projected, _ = cv2.projectPoints(objp, rvec, tvec, camera_matrix, dist_coeffs)
        error = cv2.norm(imgp, projected, cv2.NORM_L2)
        total_error += error * error
        total_points += len(objp)
    return float(np.sqrt(total_error / max(total_points, 1)))


def rectified_vertical_error(
    image_points_left: list[np.ndarray],
    image_points_right: list[np.ndarray],
    camera_left: np.ndarray,
    dist_left: np.ndarray,
    camera_right: np.ndarray,
    dist_right: np.ndarray,
    r1: np.ndarray,
    r2: np.ndarray,
    p1: np.ndarray,
    p2: np.ndarray,
) -> tuple[float, float, float]:
    values = []
    for corners_left, corners_right in zip(image_points_left, image_points_right):
        rect_left = cv2.undistortPoints(corners_left, camera_left, dist_left, R=r1, P=p1)
        rect_right = cv2.undistortPoints(corners_right, camera_right, dist_right, R=r2, P=p2)
        values.extend(np.abs(rect_left[:, 0, 1] - rect_right[:, 0, 1]).tolist())
    if not values:
        return 0.0, 0.0, 0.0
    arr = np.asarray(values, dtype=np.float32)
    return float(np.mean(arr)), float(np.median(arr)), float(np.percentile(arr, 95))


def draw_rectified_lines(image: np.ndarray) -> None:
    for y in range(40, image.shape[0], 40):
        cv2.line(image, (0, y), (image.shape[1], y), (0, 255, 255), 1, cv2.LINE_AA)


def save_debug_rectified(
    debug_dir: Path,
    pairs: list[tuple[Path, Path]],
    maps: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    limit: int = 12,
) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    map_l1, map_l2, map_r1, map_r2 = maps
    for index, (left_path, right_path) in enumerate(pairs[:limit]):
        left = cv2.imread(str(left_path))
        right = cv2.imread(str(right_path))
        if left is None or right is None:
            continue
        left_rect = cv2.remap(left, map_l1, map_l2, cv2.INTER_LINEAR)
        right_rect = cv2.remap(right, map_r1, map_r2, cv2.INTER_LINEAR)
        preview = np.hstack((left_rect, right_rect))
        draw_rectified_lines(preview)
        cv2.imwrite(str(debug_dir / f"rectified_{index:04d}.jpg"), preview)


def calibrate(args: argparse.Namespace) -> int:
    image_dir = Path(args.image_dir)
    pairs = list_image_pairs(image_dir)
    if not pairs:
        raise RuntimeError(f"No image pairs found in {image_dir}. Run capture first.")

    pattern_size = (args.pattern_cols, args.pattern_rows)
    object_template = make_object_points(pattern_size, args.square_size)
    object_points: list[np.ndarray] = []
    image_points_left: list[np.ndarray] = []
    image_points_right: list[np.ndarray] = []
    used_pairs: list[tuple[Path, Path]] = []
    image_size: tuple[int, int] | None = None

    print(f"Found {len(pairs)} image pairs. Detecting chessboard corners...")
    for left_path, right_path in pairs:
        left = cv2.imread(str(left_path))
        right = cv2.imread(str(right_path))
        if left is None or right is None or left.shape[:2] != right.shape[:2]:
            print(f"skip unreadable/size mismatch: {left_path.name}, {right_path.name}")
            continue
        current_size = (left.shape[1], left.shape[0])
        if image_size is None:
            image_size = current_size
        elif image_size != current_size:
            print(f"skip different image size: {left_path.name}, {right_path.name}")
            continue

        left_ok, left_corners = find_chessboard(left, pattern_size)
        right_ok, right_corners = find_chessboard(right, pattern_size)
        if not left_ok or not right_ok or left_corners is None or right_corners is None:
            print(f"skip no corners: {left_path.name}, {right_path.name}")
            continue
        expected_corners = pattern_size[0] * pattern_size[1]
        if len(left_corners) != expected_corners or len(right_corners) != expected_corners:
            print(
                f"skip corner count mismatch: {left_path.name}, {right_path.name} "
                f"(left {len(left_corners)}, right {len(right_corners)}, expected {expected_corners})"
            )
            continue
        right_corners, order_name, order_error = align_right_corners(left_corners, right_corners, pattern_size)

        object_points.append(object_template.copy())
        image_points_left.append(left_corners)
        image_points_right.append(right_corners)
        used_pairs.append((left_path, right_path))
        order_note = "" if order_name == "normal" else f", right order {order_name}"
        print(f"use {len(used_pairs):02d}: {left_path.name}, {right_path.name}{order_note}, dy {order_error:.2f}px")

    if image_size is None:
        raise RuntimeError("No readable image pairs.")
    if len(used_pairs) < args.min_pairs:
        raise RuntimeError(f"Need at least {args.min_pairs} valid pairs, got {len(used_pairs)}.")

    print("Calibrating left camera...")
    rms_left, camera_left, dist_left, rvecs_left, tvecs_left = cv2.calibrateCamera(
        object_points, image_points_left, image_size, None, None
    )
    print("Calibrating right camera...")
    rms_right, camera_right, dist_right, rvecs_right, tvecs_right = cv2.calibrateCamera(
        object_points, image_points_right, image_size, None, None
    )
    error_left = reprojection_error(object_points, image_points_left, rvecs_left, tvecs_left, camera_left, dist_left)
    error_right = reprojection_error(
        object_points, image_points_right, rvecs_right, tvecs_right, camera_right, dist_right
    )

    print("Calibrating stereo relationship...")
    stereo_rms, camera_left, dist_left, camera_right, dist_right, r, t, e, f = cv2.stereoCalibrate(
        object_points,
        image_points_left,
        image_points_right,
        camera_left,
        dist_left,
        camera_right,
        dist_right,
        image_size,
        criteria=CRITERIA,
        flags=cv2.CALIB_FIX_INTRINSIC if args.fix_intrinsic else 0,
    )

    r1, r2, p1, p2, q, roi1, roi2 = cv2.stereoRectify(
        camera_left,
        dist_left,
        camera_right,
        dist_right,
        image_size,
        r,
        t,
        flags=cv2.CALIB_ZERO_DISPARITY,
        alpha=args.alpha,
    )
    dy_mean, dy_median, dy_p95 = rectified_vertical_error(
        image_points_left,
        image_points_right,
        camera_left,
        dist_left,
        camera_right,
        dist_right,
        r1,
        r2,
        p1,
        p2,
    )

    output = Path(args.output)
    baseline_mm = float(np.linalg.norm(t))
    np.savez(
        output,
        image_size=np.asarray(image_size, dtype=np.int32),
        pattern_size=np.asarray(pattern_size, dtype=np.int32),
        square_size_mm=np.asarray(args.square_size, dtype=np.float32),
        camera_left=camera_left,
        dist_left=dist_left,
        camera_right=camera_right,
        dist_right=dist_right,
        r=r,
        t=t,
        e=e,
        f=f,
        r1=r1,
        r2=r2,
        p1=p1,
        p2=p2,
        q=q,
        roi1=np.asarray(roi1, dtype=np.int32),
        roi2=np.asarray(roi2, dtype=np.int32),
        baseline_mm=np.asarray(baseline_mm, dtype=np.float32),
        rms_left=np.asarray(rms_left, dtype=np.float32),
        rms_right=np.asarray(rms_right, dtype=np.float32),
        stereo_rms=np.asarray(stereo_rms, dtype=np.float32),
        reprojection_left=np.asarray(error_left, dtype=np.float32),
        reprojection_right=np.asarray(error_right, dtype=np.float32),
        rectified_dy_mean=np.asarray(dy_mean, dtype=np.float32),
        rectified_dy_median=np.asarray(dy_median, dtype=np.float32),
        rectified_dy_p95=np.asarray(dy_p95, dtype=np.float32),
        used_pairs=np.asarray([left.name for left, _ in used_pairs]),
    )

    maps = (
        cv2.initUndistortRectifyMap(camera_left, dist_left, r1, p1, image_size, cv2.CV_16SC2)[0],
        cv2.initUndistortRectifyMap(camera_left, dist_left, r1, p1, image_size, cv2.CV_16SC2)[1],
        cv2.initUndistortRectifyMap(camera_right, dist_right, r2, p2, image_size, cv2.CV_16SC2)[0],
        cv2.initUndistortRectifyMap(camera_right, dist_right, r2, p2, image_size, cv2.CV_16SC2)[1],
    )
    if args.debug_dir:
        save_debug_rectified(Path(args.debug_dir), used_pairs, maps)

    print("")
    print(f"Wrote {output}")
    print(f"Valid pairs: {len(used_pairs)}")
    print(f"Per-camera image size: {image_size[0]}x{image_size[1]}")
    print(f"Left RMS: {rms_left:.4f}, reprojection: {error_left:.4f} px")
    print(f"Right RMS: {rms_right:.4f}, reprojection: {error_right:.4f} px")
    print(f"Stereo RMS: {stereo_rms:.4f}")
    print(f"Baseline: {baseline_mm:.3f} mm")
    print(f"Rectified vertical error: mean {dy_mean:.3f} px, median {dy_median:.3f} px, p95 {dy_p95:.3f} px")
    print("")
    print("Create depth frames with:")
    print(f"  ./run_depth_camera.sh --calib {output} --width {image_size[0] * 2} --height {image_size[1]}")
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "make-board":
        return make_board(args)
    if args.command == "capture":
        return capture_pairs(args)
    if args.command == "calibrate":
        return calibrate(args)
    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
