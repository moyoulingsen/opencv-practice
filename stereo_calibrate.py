import argparse
from pathlib import Path

import cv2
import numpy as np


def parse_args():
    parser = argparse.ArgumentParser(description="Calibrate a side-by-side stereo camera from saved chessboard pairs.")
    parser.add_argument("--captures", type=Path, default=Path("captures"), help="Folder containing left_*.png/right_*.png.")
    parser.add_argument("--output", type=Path, default=Path("stereo_calibration.npz"), help="Output calibration file.")
    parser.add_argument("--cols", type=int, default=9, help="Inner chessboard corners per row.")
    parser.add_argument("--rows", type=int, default=6, help="Inner chessboard corners per column.")
    parser.add_argument("--square-mm", type=float, default=25.0, help="Chessboard square size in millimeters.")
    parser.add_argument("--baseline-mm", type=float, default=None, help="Optional known physical baseline override.")
    return parser.parse_args()


def find_pairs(captures):
    left_paths = sorted(captures.glob("left_*.png"))
    pairs = []
    for left_path in left_paths:
        right_path = captures / left_path.name.replace("left_", "right_", 1)
        if right_path.exists():
            pairs.append((left_path, right_path))
    return pairs


def make_object_points(cols, rows, square_mm):
    objp = np.zeros((rows * cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp *= square_mm
    return objp


def refine_corners(gray, corners):
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.001)
    return cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)


def main():
    args = parse_args()
    pairs = find_pairs(args.captures)
    if not pairs:
        raise RuntimeError(f"No left_*.png/right_*.png pairs found in {args.captures}.")

    pattern_size = (args.cols, args.rows)
    object_template = make_object_points(args.cols, args.rows, args.square_mm)

    object_points = []
    image_points_left = []
    image_points_right = []
    image_size = None

    for left_path, right_path in pairs:
        left = cv2.imread(str(left_path), cv2.IMREAD_GRAYSCALE)
        right = cv2.imread(str(right_path), cv2.IMREAD_GRAYSCALE)
        if left is None or right is None:
            print(f"skip unreadable pair: {left_path}, {right_path}")
            continue
        if image_size is None:
            image_size = (left.shape[1], left.shape[0])
        found_left, corners_left = cv2.findChessboardCorners(left, pattern_size)
        found_right, corners_right = cv2.findChessboardCorners(right, pattern_size)
        if not (found_left and found_right):
            print(f"skip no chessboard: {left_path.name}, {right_path.name}")
            continue

        corners_left = refine_corners(left, corners_left)
        corners_right = refine_corners(right, corners_right)
        object_points.append(object_template.copy())
        image_points_left.append(corners_left)
        image_points_right.append(corners_right)
        print(f"use pair: {left_path.name}, {right_path.name}")

    if len(object_points) < 10:
        raise RuntimeError(f"Need at least 10 good pairs; found {len(object_points)}.")

    camera_matrix_left = np.eye(3, dtype=np.float64)
    camera_matrix_right = np.eye(3, dtype=np.float64)
    dist_left = np.zeros((5, 1), dtype=np.float64)
    dist_right = np.zeros((5, 1), dtype=np.float64)

    single_criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-5)
    ret_l, camera_matrix_left, dist_left, _rvecs_l, _tvecs_l = cv2.calibrateCamera(
        object_points,
        image_points_left,
        image_size,
        camera_matrix_left,
        dist_left,
        criteria=single_criteria,
    )
    ret_r, camera_matrix_right, dist_right, _rvecs_r, _tvecs_r = cv2.calibrateCamera(
        object_points,
        image_points_right,
        image_size,
        camera_matrix_right,
        dist_right,
        criteria=single_criteria,
    )

    stereo_criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-5)
    flags = cv2.CALIB_FIX_INTRINSIC
    ret_s, camera_matrix_left, dist_left, camera_matrix_right, dist_right, r, t, e, f = cv2.stereoCalibrate(
        object_points,
        image_points_left,
        image_points_right,
        camera_matrix_left,
        dist_left,
        camera_matrix_right,
        dist_right,
        image_size,
        criteria=stereo_criteria,
        flags=flags,
    )

    baseline_from_calibration = float(np.linalg.norm(t))
    baseline_mm = float(args.baseline_mm) if args.baseline_mm else baseline_from_calibration
    if args.baseline_mm:
        t = t * (baseline_mm / baseline_from_calibration)

    r1, r2, p1, p2, q, roi1, roi2 = cv2.stereoRectify(
        camera_matrix_left,
        dist_left,
        camera_matrix_right,
        dist_right,
        image_size,
        r,
        t,
        flags=cv2.CALIB_ZERO_DISPARITY,
        alpha=0,
    )

    map1x, map1y = cv2.initUndistortRectifyMap(
        camera_matrix_left, dist_left, r1, p1, image_size, cv2.CV_32FC1
    )
    map2x, map2y = cv2.initUndistortRectifyMap(
        camera_matrix_right, dist_right, r2, p2, image_size, cv2.CV_32FC1
    )
    focal_px = float(p1[0, 0])

    np.savez(
        args.output,
        image_size=np.array(image_size),
        camera_matrix_left=camera_matrix_left,
        camera_matrix_right=camera_matrix_right,
        dist_left=dist_left,
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
        roi1=np.array(roi1),
        roi2=np.array(roi2),
        map1x=map1x,
        map1y=map1y,
        map2x=map2x,
        map2y=map2y,
        focal_px=np.array(focal_px),
        baseline_mm=np.array(baseline_mm),
        square_mm=np.array(args.square_mm),
        reprojection_left=np.array(ret_l),
        reprojection_right=np.array(ret_r),
        reprojection_stereo=np.array(ret_s),
    )

    print()
    print(f"saved calibration: {args.output}")
    print(f"good pairs: {len(object_points)}")
    print(f"left reprojection error: {ret_l:.4f}")
    print(f"right reprojection error: {ret_r:.4f}")
    print(f"stereo reprojection error: {ret_s:.4f}")
    print(f"baseline from calibration: {baseline_from_calibration:.2f} mm")
    print(f"baseline used: {baseline_mm:.2f} mm")
    print(f"rectified focal length: {focal_px:.2f} px")


if __name__ == "__main__":
    main()
