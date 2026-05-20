#!/usr/bin/env python3
"""Generate depth images from the MF287/TB2 UVC stereo camera.

The MF287/TB2 exposes a standard side-by-side video stream instead of a native
depth stream. This program turns that stream into three depth artifacts:

  depth_raw.npy  float32 depth in meters for programs
  depth_mm.png   uint16 depth in millimeters for OpenCV/ROS style workflows
  depth_vis.png  colored visualization for humans
"""

from __future__ import annotations

import argparse
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Calibration:
    image_size: tuple[int, int]
    map_l1: np.ndarray
    map_l2: np.ndarray
    map_r1: np.ndarray
    map_r2: np.ndarray
    q: np.ndarray
    focal_px: float
    baseline_m: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MF287 depth image generator.")
    parser.add_argument("--device", type=int, default=4, help="Video index, e.g. 4 for /dev/video4.")
    parser.add_argument("--width", type=int, default=2560, help="Full side-by-side capture width.")
    parser.add_argument("--height", type=int, default=720, help="Full side-by-side capture height.")
    parser.add_argument("--fps", type=int, default=30, help="Requested FPS.")
    parser.add_argument("--swap", action="store_true", help="Swap left/right images before matching.")
    parser.add_argument(
        "--no-balance",
        action="store_true",
        help="Do not normalize right-image brightness to the left image before stereo matching.",
    )
    parser.add_argument("--manual-controls", action="store_true", help="Do not reset UVC exposure/white-balance controls.")
    parser.add_argument("--exposure", type=int, default=-1, help="Manual exposure value. -1 keeps auto exposure.")
    parser.add_argument("--gain", type=int, default=0, help="Manual gain value used with --exposure.")
    parser.add_argument("--calib", default="", help="Calibration file from calibrate_mf287.py.")
    parser.add_argument("--output-dir", default="mf287_depth_output", help="Directory for saved depth files.")
    parser.add_argument("--prefix", default="depth", help="File prefix, default writes depth_raw.npy/depth_mm.png/depth_vis.png.")
    parser.add_argument("--save-every", type=int, default=0, help="Auto-save every N frames. 0 saves only on key press.")
    parser.add_argument(
        "--stream-files",
        action="store_true",
        help="Continuously overwrite depth_raw.npy/depth_mm.png/depth_vis.png with the latest frame.",
    )
    parser.add_argument(
        "--stream-every",
        type=int,
        default=1,
        help="When --stream-files is set, write every N frames.",
    )
    parser.add_argument("--max-frames", type=int, default=0, help="Stop after N frames. 0 runs until q/ESC/Ctrl-C.")
    parser.add_argument("--no-preview", action="store_true", help="Run without display windows.")
    parser.add_argument("--max-depth", type=float, default=5.0, help="Maximum valid depth in meters.")
    parser.add_argument("--min-depth", type=float, default=0.35, help="Minimum valid depth in meters.")
    parser.add_argument("--num-disparities", type=int, default=96, help="SGBM disparity range, multiple of 16.")
    parser.add_argument("--block-size", type=int, default=5, help="SGBM block size, odd number >= 3.")
    parser.add_argument("--uniqueness", type=int, default=10, help="SGBM uniqueness ratio.")
    parser.add_argument("--speckle-window", type=int, default=120, help="SGBM speckle window size.")
    parser.add_argument("--speckle-range", type=int, default=2, help="SGBM speckle range.")
    parser.add_argument(
        "--relative-scale",
        type=float,
        default=30.0,
        help="Pseudo focal*baseline value for uncalibrated relative depth preview.",
    )
    return parser.parse_args()


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

    cmd = ["v4l2-ctl", "-d", device, "--set-ctrl=" + ",".join(f"{k}={v}" for k, v in controls.items())]
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


def load_calibration(path: str, image_size: tuple[int, int]) -> Calibration:
    data = np.load(path)
    calib_size = tuple(int(v) for v in data["image_size"])
    if calib_size != image_size:
        raise RuntimeError(
            f"Calibration image size is {calib_size[0]}x{calib_size[1]}, "
            f"but camera per-eye image size is {image_size[0]}x{image_size[1]}."
        )

    camera_left = data["camera_left"]
    dist_left = data["dist_left"]
    camera_right = data["camera_right"]
    dist_right = data["dist_right"]
    r1 = data["r1"]
    r2 = data["r2"]
    p1 = data["p1"]
    p2 = data["p2"]
    q = data["q"]
    map_l1, map_l2 = cv2.initUndistortRectifyMap(camera_left, dist_left, r1, p1, image_size, cv2.CV_16SC2)
    map_r1, map_r2 = cv2.initUndistortRectifyMap(camera_right, dist_right, r2, p2, image_size, cv2.CV_16SC2)
    focal_px = float(p1[0, 0])
    baseline_m = float(abs(1.0 / q[3, 2])) / 1000.0 if q[3, 2] != 0 else float(data["baseline_mm"]) / 1000.0
    return Calibration(image_size, map_l1, map_l2, map_r1, map_r2, q, focal_px, baseline_m)


def rectify_pair(left: np.ndarray, right: np.ndarray, calib: Calibration) -> tuple[np.ndarray, np.ndarray]:
    left_rect = cv2.remap(left, calib.map_l1, calib.map_l2, cv2.INTER_LINEAR)
    right_rect = cv2.remap(right, calib.map_r1, calib.map_r2, cv2.INTER_LINEAR)
    return left_rect, right_rect


def balance_pair_brightness(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    left_gray = cv2.cvtColor(left, cv2.COLOR_BGR2GRAY)
    right_gray = cv2.cvtColor(right, cv2.COLOR_BGR2GRAY)
    left_mean = float(left_gray.mean())
    right_mean = float(right_gray.mean())
    if right_mean < 1.0:
        return left, right
    scale = np.clip(left_mean / right_mean, 0.5, 2.5)
    balanced_right = cv2.convertScaleAbs(right, alpha=scale, beta=0)
    return left, balanced_right


def create_matcher(args: argparse.Namespace) -> cv2.StereoSGBM:
    block_size = max(3, args.block_size | 1)
    num_disparities = max(16, (args.num_disparities // 16) * 16)
    return cv2.StereoSGBM_create(
        minDisparity=0,
        numDisparities=num_disparities,
        blockSize=block_size,
        P1=8 * 3 * block_size * block_size,
        P2=32 * 3 * block_size * block_size,
        disp12MaxDiff=1,
        uniquenessRatio=args.uniqueness,
        speckleWindowSize=args.speckle_window,
        speckleRange=args.speckle_range,
        preFilterCap=31,
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
    )


def compute_disparity(left: np.ndarray, right: np.ndarray, matcher: cv2.StereoMatcher) -> np.ndarray:
    gray_left = cv2.cvtColor(left, cv2.COLOR_BGR2GRAY)
    gray_right = cv2.cvtColor(right, cv2.COLOR_BGR2GRAY)
    disparity = matcher.compute(gray_left, gray_right).astype(np.float32) / 16.0
    disparity[disparity <= 0.0] = np.nan
    return disparity


def disparity_to_depth(
    disparity: np.ndarray,
    calib: Calibration | None,
    relative_scale: float,
    min_depth: float,
    max_depth: float,
) -> np.ndarray:
    if calib is not None:
        scale = calib.focal_px * calib.baseline_m
    else:
        scale = relative_scale

    depth = scale / disparity
    invalid = ~np.isfinite(depth) | (depth < min_depth) | (depth > max_depth)
    depth = depth.astype(np.float32)
    depth[invalid] = 0.0
    return depth


def make_depth_mm(depth_m: np.ndarray) -> np.ndarray:
    depth_mm = np.clip(depth_m * 1000.0, 0.0, 65535.0)
    return depth_mm.astype(np.uint16)


def make_depth_vis(depth_m: np.ndarray, min_depth: float, max_depth: float) -> np.ndarray:
    valid = depth_m > 0.0
    normalized = np.zeros(depth_m.shape, dtype=np.uint8)
    if np.any(valid):
        clipped = np.clip(depth_m, min_depth, max_depth)
        normalized = ((max_depth - clipped) * 255.0 / max(max_depth - min_depth, 1e-6)).astype(np.uint8)
        normalized[~valid] = 0
    vis = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
    vis[~valid] = (0, 0, 0)
    return vis


def make_disparity_vis(disparity: np.ndarray) -> np.ndarray:
    valid = np.isfinite(disparity) & (disparity > 0.0)
    normalized = np.zeros(disparity.shape, dtype=np.uint8)
    if np.any(valid):
        lo = float(np.percentile(disparity[valid], 3))
        hi = float(np.percentile(disparity[valid], 97))
        if hi <= lo:
            hi = lo + 1.0
        normalized = np.clip((disparity - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)
        normalized[~valid] = 0
    vis = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
    vis[~valid] = (0, 0, 0)
    return vis


def draw_hud(image: np.ndarray, text: str, detail: str, stats: str) -> None:
    cv2.rectangle(image, (8, 8), (1050, 102), (0, 0, 0), -1)
    cv2.putText(image, text, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(
        image,
        detail,
        (20, 64),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (230, 230, 230),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        image,
        stats,
        (20, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (230, 230, 230),
        1,
        cv2.LINE_AA,
    )


def image_stats(left: np.ndarray, right: np.ndarray, depth_mm: np.ndarray) -> tuple[float, float, float]:
    gray_left = cv2.cvtColor(left, cv2.COLOR_BGR2GRAY)
    gray_right = cv2.cvtColor(right, cv2.COLOR_BGR2GRAY)
    valid_ratio = 100.0 * float(np.count_nonzero(depth_mm)) / float(depth_mm.size)
    return float(gray_left.mean()), float(gray_right.mean()), valid_ratio


def save_depth_outputs(
    output_dir: Path,
    prefix: str,
    depth_m: np.ndarray,
    depth_mm: np.ndarray,
    depth_vis: np.ndarray,
    left: np.ndarray,
    right: np.ndarray,
    disparity_vis: np.ndarray | None,
    indexed: bool,
    index: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_{index:04d}" if indexed else ""
    raw_path = output_dir / f"{prefix}{suffix}_raw.npy"
    mm_path = output_dir / f"{prefix}{suffix}_mm.png"
    vis_path = output_dir / f"{prefix}{suffix}_vis.png"
    left_path = output_dir / f"{prefix}{suffix}_left.png"
    right_path = output_dir / f"{prefix}{suffix}_right.png"
    disparity_path = output_dir / f"{prefix}{suffix}_disparity_vis.png"

    np.save(raw_path, depth_m.astype(np.float32))
    cv2.imwrite(str(mm_path), depth_mm)
    cv2.imwrite(str(vis_path), depth_vis)
    cv2.imwrite(str(left_path), left)
    cv2.imwrite(str(right_path), right)
    if disparity_vis is not None:
        cv2.imwrite(str(disparity_path), disparity_vis)
    print(f"Wrote {raw_path}, {mm_path}, {vis_path}")


def write_latest_outputs(
    output_dir: Path,
    prefix: str,
    depth_m: np.ndarray,
    depth_mm: np.ndarray,
    depth_vis: np.ndarray,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / f"{prefix}_raw.npy", depth_m.astype(np.float32))
    cv2.imwrite(str(output_dir / f"{prefix}_mm.png"), depth_mm)
    cv2.imwrite(str(output_dir / f"{prefix}_vis.png"), depth_vis)


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    cap = open_camera(args)
    matcher = create_matcher(args)
    calib: Calibration | None = None
    loaded_calib = False
    frame_index = 0
    save_index = 0
    last_time = time.monotonic()
    last_report_time = time.monotonic()
    fps = 0.0
    stream_every = max(1, args.stream_every)

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                print("No frame received.")
                time.sleep(0.1)
                continue

            left, right = split_side_by_side(frame, args.swap)
            per_eye_size = (left.shape[1], left.shape[0])
            if args.calib and not loaded_calib:
                calib = load_calibration(args.calib, per_eye_size)
                loaded_calib = True
                print(f"Loaded calibration: {args.calib}")
                print(f"Metric depth enabled. Baseline: {calib.baseline_m * 1000.0:.3f} mm")
            if calib is not None:
                left, right = rectify_pair(left, right, calib)
            if not args.no_balance:
                left, right = balance_pair_brightness(left, right)

            disparity = compute_disparity(left, right, matcher)
            depth_m = disparity_to_depth(disparity, calib, args.relative_scale, args.min_depth, args.max_depth)
            depth_mm = make_depth_mm(depth_m)
            depth_vis = make_depth_vis(depth_m, args.min_depth, args.max_depth)
            disparity_vis = make_disparity_vis(disparity)

            now = time.monotonic()
            dt = now - last_time
            last_time = now
            if dt > 0:
                fps = fps * 0.85 + (1.0 / dt) * 0.15

            should_save = args.save_every > 0 and frame_index % args.save_every == 0
            if should_save:
                save_depth_outputs(
                    output_dir, args.prefix, depth_m, depth_mm, depth_vis, left, right, disparity_vis, True, save_index
                )
                save_index += 1

            if args.stream_files and frame_index % stream_every == 0:
                write_latest_outputs(output_dir, args.prefix, depth_m, depth_mm, depth_vis)
                if args.no_preview and now - last_report_time >= 1.0:
                    valid_ratio = 100.0 * float(np.count_nonzero(depth_mm)) / float(depth_mm.size)
                    print(
                        f"streaming latest depth | frame {frame_index} | FPS {fps:4.1f} | "
                        f"valid {valid_ratio:4.1f}% | {output_dir}"
                    )
                    last_report_time = now

            if not args.no_preview:
                left_mean, right_mean, valid_ratio = image_stats(left, right, depth_mm)
                preview_left = cv2.resize(left, (640, 360), interpolation=cv2.INTER_AREA)
                preview_right = cv2.resize(right, (640, 360), interpolation=cv2.INTER_AREA)
                stereo_preview = np.hstack((preview_left, preview_right))
                mode = "metric depth" if calib is not None else "relative depth, calibrate for meters"
                output_mode = "streaming latest files" if args.stream_files else "press s to save files"
                draw_hud(
                    stereo_preview,
                    f"/dev/video{args.device} {frame.shape[1]}x{frame.shape[0]} FPS {fps:4.1f} | {mode}",
                    f"{output_mode} | q/ESC quit | disp {max(16, (args.num_disparities // 16) * 16)} | depth {args.min_depth:.2f}-{args.max_depth:.1f}m",
                    f"valid depth {valid_ratio:4.1f}% | left brightness {left_mean:5.1f} | right brightness {right_mean:5.1f}",
                )
                cv2.imshow("MF287 left | right", stereo_preview)
                cv2.imshow("MF287 depth_vis", cv2.resize(depth_vis, (640, 360), interpolation=cv2.INTER_AREA))

                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
                if key == ord("s"):
                    save_depth_outputs(
                        output_dir, args.prefix, depth_m, depth_mm, depth_vis, left, right, disparity_vis, False, 0
                    )

            frame_index += 1
            if args.no_preview and args.save_every == 0:
                if args.stream_files:
                    if args.max_frames > 0 and frame_index >= args.max_frames:
                        break
                else:
                    save_depth_outputs(
                        output_dir, args.prefix, depth_m, depth_mm, depth_vis, left, right, disparity_vis, False, 0
                    )
                    break
            elif args.max_frames > 0 and frame_index >= args.max_frames:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
