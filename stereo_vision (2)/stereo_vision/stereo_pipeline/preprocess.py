from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def balance_pair_brightness(
    left: np.ndarray,
    right: np.ndarray,
    cfg: dict[str, Any] | None,
) -> tuple[np.ndarray, np.ndarray]:
    cfg = cfg or {}
    if not bool(cfg.get("enabled", False)):
        return left, right

    left_mean = _gray_mean(left)
    right_mean = _gray_mean(right)
    if left_mean <= 1.0 or right_mean <= 1.0:
        return left, right

    mode = str(cfg.get("mode", "pair_mean")).lower()
    min_scale = float(cfg.get("min_scale", 0.5))
    max_scale = float(cfg.get("max_scale", 2.0))

    if mode == "right_to_left":
        return left, _scale_image(right, left_mean / right_mean, min_scale, max_scale)
    if mode == "left_to_right":
        return _scale_image(left, right_mean / left_mean, min_scale, max_scale), right

    target = float(cfg.get("target_mean", 0.0))
    if target <= 0.0:
        target = 0.5 * (left_mean + right_mean)
    return (
        _scale_image(left, target / left_mean, min_scale, max_scale),
        _scale_image(right, target / right_mean, min_scale, max_scale),
    )


def _gray_mean(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(gray.mean())


def _scale_image(image: np.ndarray, scale: float, min_scale: float, max_scale: float) -> np.ndarray:
    scale = float(np.clip(scale, min_scale, max_scale))
    if abs(scale - 1.0) < 1e-3:
        return image
    return cv2.convertScaleAbs(image, alpha=scale, beta=0)
