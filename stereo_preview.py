import argparse
from pathlib import Path

import cv2
import numpy as np


DEFAULT_CAMERA_INDEX = 1
DEFAULT_FRAME_WIDTH = 2560
DEFAULT_FRAME_HEIGHT = 720
DEFAULT_FPS = 30


def parse_args():
    parser = argparse.ArgumentParser(
        description="Preview an MF287-style side-by-side stereo camera and show disparity/depth."
    )
    parser.add_argument("--camera", type=int, default=DEFAULT_CAMERA_INDEX, help="OpenCV camera index.")
    parser.add_argument("--width", type=int, default=DEFAULT_FRAME_WIDTH, help="Requested full frame width.")
    parser.add_argument("--height", type=int, default=DEFAULT_FRAME_HEIGHT, help="Requested full frame height.")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help="Requested FPS.")
    parser.add_argument("--baseline-mm", type=float, default=60.0, help="Stereo baseline in millimeters.")
    parser.add_argument("--hfov-deg", type=float, default=100.0, help="Horizontal field of view of one lens.")
    parser.add_argument(
        "--calibration",
        type=Path,
        default=Path("stereo_calibration.npz"),
        help="Optional calibration file produced by stereo_calibrate.py.",
    )
    parser.add_argument("--save-dir", type=Path, default=Path("captures"), help="Directory for saved frames.")
    parser.add_argument("--no-depth", action="store_true", help="Only show the split stereo image.")
    parser.add_argument(
        "--settings",
        action="store_true",
        help="Open the DirectShow camera settings dialog after opening the camera.",
    )
    return parser.parse_args()


def load_calibration(path):
    if not path.exists():
        return None
    data = np.load(path)
    required = {"map1x", "map1y", "map2x", "map2y", "q", "focal_px", "baseline_mm"}
    if not required.issubset(set(data.files)):
        missing = ", ".join(sorted(required.difference(set(data.files))))
        raise ValueError(f"{path} is missing calibration keys: {missing}")
    return {
        "map1x": data["map1x"],
        "map1y": data["map1y"],
        "map2x": data["map2x"],
        "map2y": data["map2y"],
        "q": data["q"],
        "focal_px": float(data["focal_px"]),
        "baseline_mm": float(data["baseline_mm"]),
    }


def make_matcher(num_disparities, block_size, uniqueness_ratio, speckle_window_size, speckle_range):
    num_disparities = max(16, int(num_disparities // 16 * 16))
    block_size = max(3, int(block_size) | 1)
    p1 = 8 * 3 * block_size * block_size
    p2 = 32 * 3 * block_size * block_size
    return cv2.StereoSGBM_create(
        minDisparity=0,
        numDisparities=num_disparities,
        blockSize=block_size,
        P1=p1,
        P2=p2,
        disp12MaxDiff=1,
        uniquenessRatio=int(uniqueness_ratio),
        speckleWindowSize=int(speckle_window_size),
        speckleRange=int(speckle_range),
        preFilterCap=31,
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
    )


def create_controls():
    cv2.namedWindow("controls", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("controls", 520, 520)
    cv2.createTrackbar("auto exp 0=manual", "controls", 0, 1, lambda _value: None)
    cv2.createTrackbar("exposure -13..0", "controls", 0, 13, lambda _value: None)
    cv2.createTrackbar("gain 0..255", "controls", 0, 255, lambda _value: None)
    cv2.createTrackbar("brightness -64..64", "controls", 64, 128, lambda _value: None)
    cv2.createTrackbar("contrast 0..128", "controls", 32, 128, lambda _value: None)
    cv2.createTrackbar("saturation 0..128", "controls", 36, 128, lambda _value: None)
    cv2.createTrackbar("gamma 1..500", "controls", 99, 500, lambda _value: None)
    cv2.createTrackbar("numDisp x16", "controls", 8, 16, lambda _value: None)
    cv2.createTrackbar("block odd", "controls", 5, 21, lambda _value: None)
    cv2.createTrackbar("uniqueness", "controls", 8, 30, lambda _value: None)
    cv2.createTrackbar("speckle win", "controls", 50, 200, lambda _value: None)
    cv2.createTrackbar("speckle range", "controls", 2, 10, lambda _value: None)


def read_controls(cap):
    auto_exposure_enabled = cv2.getTrackbarPos("auto exp 0=manual", "controls")
    exposure_slider = cv2.getTrackbarPos("exposure -13..0", "controls")
    exposure = exposure_slider - 13
    gain = cv2.getTrackbarPos("gain 0..255", "controls")
    brightness = cv2.getTrackbarPos("brightness -64..64", "controls") - 64
    contrast = cv2.getTrackbarPos("contrast 0..128", "controls")
    saturation = cv2.getTrackbarPos("saturation 0..128", "controls")
    gamma = max(1, cv2.getTrackbarPos("gamma 1..500", "controls"))
    num_disp = max(1, cv2.getTrackbarPos("numDisp x16", "controls")) * 16
    block_size = cv2.getTrackbarPos("block odd", "controls")
    uniqueness = cv2.getTrackbarPos("uniqueness", "controls")
    speckle_win = cv2.getTrackbarPos("speckle win", "controls")
    speckle_range = cv2.getTrackbarPos("speckle range", "controls")

    # DirectShow commonly uses 0.25 for manual exposure and 0.75 for auto.
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75 if auto_exposure_enabled else 0.25)
    cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
    cap.set(cv2.CAP_PROP_GAIN, gain)
    cap.set(cv2.CAP_PROP_BRIGHTNESS, brightness)
    cap.set(cv2.CAP_PROP_CONTRAST, contrast)
    cap.set(cv2.CAP_PROP_SATURATION, saturation)
    cap.set(cv2.CAP_PROP_GAMMA, gamma)

    return (
        auto_exposure_enabled,
        exposure,
        gain,
        brightness,
        contrast,
        saturation,
        gamma,
        num_disp,
        block_size,
        uniqueness,
        speckle_win,
        speckle_range,
    )


def split_stereo_frame(frame):
    height, width = frame.shape[:2]
    half_width = width // 2
    left = frame[:, :half_width].copy()
    right = frame[:, half_width : half_width * 2].copy()
    return left, right


def focal_from_hfov(width, hfov_deg):
    hfov_rad = np.deg2rad(hfov_deg)
    return width / (2.0 * np.tan(hfov_rad / 2.0))


def resize_for_screen(image, max_width=1280, max_height=720):
    height, width = image.shape[:2]
    scale = min(max_width / width, max_height / height, 1.0)
    if scale >= 1.0:
        return image
    return cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)


def draw_status(image, lines):
    y = 26
    for line in lines:
        cv2.putText(image, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(image, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 1, cv2.LINE_AA)
        y += 24


def normalize_disparity(disparity):
    valid = disparity > 0
    visual = np.zeros(disparity.shape, dtype=np.uint8)
    if np.any(valid):
        lo, hi = np.percentile(disparity[valid], [2, 98])
        if hi > lo:
            clipped = np.clip(disparity, lo, hi)
            visual = ((clipped - lo) * 255.0 / (hi - lo)).astype(np.uint8)
    return cv2.applyColorMap(visual, cv2.COLORMAP_TURBO)


def center_distance_mm(disparity, focal_px, baseline_mm):
    height, width = disparity.shape
    box_w = max(24, width // 12)
    box_h = max(24, height // 12)
    x1 = width // 2 - box_w // 2
    y1 = height // 2 - box_h // 2
    roi = disparity[y1 : y1 + box_h, x1 : x1 + box_w]
    valid = roi[roi > 1.0]
    if valid.size < 20:
        return None, (x1, y1, box_w, box_h)
    disp = float(np.median(valid))
    return focal_px * baseline_mm / disp, (x1, y1, box_w, box_h)


def main():
    args = parse_args()
    args.save_dir.mkdir(parents=True, exist_ok=True)

    calibration = load_calibration(args.calibration)

    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera index {args.camera}. Close other camera apps and replug USB.")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, args.fps)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUY2"))
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    cap.set(cv2.CAP_PROP_GAIN, 0)
    cap.set(cv2.CAP_PROP_BRIGHTNESS, 0)
    cap.set(cv2.CAP_PROP_CONTRAST, 32)
    cap.set(cv2.CAP_PROP_SATURATION, 36)
    cap.set(cv2.CAP_PROP_GAMMA, 99)
    cap.set(cv2.CAP_PROP_EXPOSURE, -13)

    if args.settings:
        cap.set(cv2.CAP_PROP_SETTINGS, 1)

    create_controls()

    focal_px = None
    baseline_mm = args.baseline_mm
    matcher = None
    last_matcher_params = None
    saved_count = 0

    while True:
        (
            auto_exposure_enabled,
            exposure,
            gain,
            brightness,
            contrast,
            saturation,
            gamma,
            num_disp,
            block_size,
            uniqueness,
            speckle_win,
            speckle_range,
        ) = read_controls(cap)

        ok, frame = cap.read()
        if not ok or frame is None:
            print("Failed to read frame.")
            break

        left, right = split_stereo_frame(frame)

        if calibration:
            left_view = cv2.remap(left, calibration["map1x"], calibration["map1y"], cv2.INTER_LINEAR)
            right_view = cv2.remap(right, calibration["map2x"], calibration["map2y"], cv2.INTER_LINEAR)
            focal_px = calibration["focal_px"]
            baseline_mm = calibration["baseline_mm"]
            calibration_status = "calibrated"
        else:
            left_view = left
            right_view = right
            focal_px = focal_from_hfov(left.shape[1], args.hfov_deg)
            calibration_status = "uncalibrated approx"

        stereo_view = np.hstack([left_view, right_view])
        gray = cv2.cvtColor(stereo_view, cv2.COLOR_BGR2GRAY)
        mean_brightness = float(gray.mean())

        status = [
            f"camera={args.camera} frame={frame.shape[1]}x{frame.shape[0]} split={left.shape[1]}x{left.shape[0]}",
            (
                f"autoExp={auto_exposure_enabled} exposure={exposure} gain={gain} "
                f"bright={brightness} contrast={contrast} sat={saturation} gamma={gamma} mean={mean_brightness:.1f}"
            ),
            "keys: q quit | s save pair | p native settings | use controls window to tune",
        ]
        draw_status(stereo_view, status)
        cv2.imshow("stereo left | right", resize_for_screen(stereo_view, max_width=1500, max_height=760))

        if not args.no_depth:
            params = (num_disp, block_size, uniqueness, speckle_win, speckle_range)
            if matcher is None or params != last_matcher_params:
                matcher = make_matcher(*params)
                last_matcher_params = params

            left_gray = cv2.cvtColor(left_view, cv2.COLOR_BGR2GRAY)
            right_gray = cv2.cvtColor(right_view, cv2.COLOR_BGR2GRAY)
            disparity = matcher.compute(left_gray, right_gray).astype(np.float32) / 16.0
            depth_color = normalize_disparity(disparity)
            distance_mm, box = center_distance_mm(disparity, focal_px, baseline_mm)
            x, y, w, h = box
            cv2.rectangle(depth_color, (x, y), (x + w, y + h), (255, 255, 255), 2)

            if distance_mm is None:
                distance_text = "center distance: no valid disparity"
            else:
                distance_text = f"center distance: {distance_mm / 1000.0:.2f} m"

            depth_lines = [
                f"{calibration_status} | baseline={baseline_mm:.1f}mm focal={focal_px:.1f}px",
                f"{distance_text}",
                f"numDisp={num_disp} block={max(3, int(block_size) | 1)} uniqueness={uniqueness}",
            ]
            draw_status(depth_color, depth_lines)
            cv2.imshow("disparity / depth preview", resize_for_screen(depth_color, max_width=900, max_height=720))

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q") or key == 27:
            break
        if key == ord("p"):
            cap.set(cv2.CAP_PROP_SETTINGS, 1)
        if key == ord("s"):
            saved_count += 1
            left_path = args.save_dir / f"left_{saved_count:04d}.png"
            right_path = args.save_dir / f"right_{saved_count:04d}.png"
            full_path = args.save_dir / f"stereo_{saved_count:04d}.png"
            cv2.imwrite(str(left_path), left)
            cv2.imwrite(str(right_path), right)
            cv2.imwrite(str(full_path), frame)
            print(f"saved {left_path}, {right_path}, {full_path}")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
