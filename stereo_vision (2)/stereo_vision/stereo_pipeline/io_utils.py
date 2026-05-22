from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time
from typing import Iterable

import cv2
import numpy as np


IMAGE_EXTENSIONS = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tif", "*.tiff")


def ensure_dir(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def list_images(directory: str | Path) -> list[Path]:
    root = Path(directory)
    files: list[Path] = []
    for pattern in IMAGE_EXTENSIONS:
        files.extend(root.glob(pattern))
    return sorted(files)


def pair_images(left_dir: str | Path, right_dir: str | Path) -> list[tuple[Path, Path]]:
    left_files = list_images(left_dir)
    right_files = list_images(right_dir)
    if len(left_files) != len(right_files):
        raise ValueError(
            f"Left/right image count mismatch: {len(left_files)} vs {len(right_files)}"
        )
    if not left_files:
        raise ValueError("No calibration images found.")

    pairs: list[tuple[Path, Path]] = []
    for left_path, right_path in zip(left_files, right_files, strict=True):
        if left_path.stem != right_path.stem:
            raise ValueError(
                f"Image names do not match: {left_path.name} vs {right_path.name}"
            )
        pairs.append((left_path, right_path))
    return pairs


def read_color_image(path: str | Path):
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Failed to load image: {path}")
    return image


def read_gray_image(path: str | Path):
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"Failed to load image: {path}")
    return image


def capture_backend_id(runtime: dict | None = None) -> int:
    backend_name = str((runtime or {}).get("camera_backend", "auto")).lower()
    backends = {
        "any": cv2.CAP_ANY,
        "auto": cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_V4L2,
        "dshow": cv2.CAP_DSHOW,
        "v4l2": cv2.CAP_V4L2,
    }
    if backend_name not in backends:
        raise ValueError(f"Unsupported camera_backend: {backend_name}")
    return backends[backend_name]


def open_video_capture(camera_id: int, runtime: dict | None = None) -> cv2.VideoCapture:
    configure_uvc_controls(camera_id, runtime)
    backend = capture_backend_id(runtime)
    cap = cv2.VideoCapture(int(camera_id), backend)
    if not cap.isOpened() and backend != cv2.CAP_ANY:
        cap.release()
        cap = cv2.VideoCapture(int(camera_id), cv2.CAP_ANY)

    fourcc = str((runtime or {}).get("fourcc", "")).strip()
    if len(fourcc) == 4:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc.upper()))
    if runtime is not None:
        if "frame_width" in runtime:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(runtime["frame_width"]))
        if "frame_height" in runtime:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(runtime["frame_height"]))
        if "fps" in runtime:
            cap.set(cv2.CAP_PROP_FPS, int(runtime["fps"]))
    configure_uvc_controls(camera_id, runtime)
    return cap


def configure_uvc_controls(camera_id: int, runtime: dict | None = None) -> None:
    camera_controls = (runtime or {}).get("camera_controls", {})
    if not bool(camera_controls.get("enabled", False)):
        return

    device = f"/dev/video{int(camera_id)}"
    ordered_keys = (
        "auto_exposure",
        "exposure_time_absolute",
        "gain",
        "brightness",
        "contrast",
        "white_balance_automatic",
        "white_balance_temperature",
        "backlight_compensation",
    )
    for key in ordered_keys:
        if key not in camera_controls:
            continue
        cmd = ["v4l2-ctl", "-d", device, f"--set-ctrl={key}={int(camera_controls[key])}"]
        try:
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return
        if key in {"auto_exposure", "white_balance_automatic"}:
            time.sleep(0.02)


def split_combined_stereo_frame(
    frame: np.ndarray,
    layout: str = "left_right",
) -> tuple[np.ndarray, np.ndarray]:
    if frame is None or frame.size == 0:
        raise ValueError("Input frame is empty.")
    layout = layout.lower()
    height, width = frame.shape[:2]
    if layout == "left_right":
        if width % 2 != 0:
            raise ValueError(f"Combined frame width must be even, got {width}")
        mid = width // 2
        return frame[:, :mid].copy(), frame[:, mid:].copy()
    if layout == "top_bottom":
        if height % 2 != 0:
            raise ValueError(f"Combined frame height must be even, got {height}")
        mid = height // 2
        return frame[:mid, :].copy(), frame[mid:, :].copy()
    raise ValueError(f"Unsupported split layout: {layout}")


def summarize_numeric(values: Iterable[float]) -> dict[str, float]:
    values = list(values)
    if not values:
        return {"count": 0, "min": 0.0, "max": 0.0, "mean": 0.0}
    return {
        "count": len(values),
        "min": float(min(values)),
        "max": float(max(values)),
        "mean": float(sum(values) / len(values)),
    }
