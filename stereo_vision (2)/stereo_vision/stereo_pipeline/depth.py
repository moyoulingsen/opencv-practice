from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from .preprocess import balance_pair_brightness


class StereoDepthPipeline:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.output_dir = Path(config["paths"]["output_dir"])
        self.matcher_cfg = config["matcher"]
        self.preprocessing_cfg = config.get("preprocessing", {})
        self.stereo_params = self._load_stereo_yaml()
        self.maps = np.load(self.output_dir / "rectification_maps.npz")
        self.q_matrix = self.maps["Q"]
        self.left_matcher, self.right_matcher = self._build_matchers()
        self.wls_filter = self._build_wls_filter()

    def rectify_pair(self, left_image: np.ndarray, right_image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        left_rectified = cv2.remap(
            left_image,
            self.maps["left_map_x"],
            self.maps["left_map_y"],
            cv2.INTER_LINEAR,
        )
        right_rectified = cv2.remap(
            right_image,
            self.maps["right_map_x"],
            self.maps["right_map_y"],
            cv2.INTER_LINEAR,
        )
        return left_rectified, right_rectified

    def compute(self, left_image: np.ndarray, right_image: np.ndarray) -> dict[str, np.ndarray]:
        left_rectified, right_rectified = self.rectify_pair(left_image, right_image)
        left_matched, right_matched = balance_pair_brightness(
            left_rectified,
            right_rectified,
            self.preprocessing_cfg.get("brightness_balance", {}),
        )
        left_gray = cv2.cvtColor(left_matched, cv2.COLOR_BGR2GRAY)
        right_gray = cv2.cvtColor(right_matched, cv2.COLOR_BGR2GRAY)

        left_disp = self.left_matcher.compute(left_gray, right_gray)
        right_disp = self.right_matcher.compute(right_gray, left_gray)

        if self.wls_filter is not None:
            filtered = self.wls_filter.filter(left_disp, left_matched, disparity_map_right=right_disp)
            disparity = filtered.astype(np.float32) / 16.0
        else:
            disparity = left_disp.astype(np.float32) / 16.0

        disparity[disparity <= 0.0] = np.nan
        points_3d = cv2.reprojectImageTo3D(disparity, self.q_matrix, handleMissingValues=True)
        depth_m = points_3d[:, :, 2]
        depth_m[~np.isfinite(depth_m)] = np.nan

        vis = self._colorize_disparity(disparity)
        return {
            "left_rectified": left_rectified,
            "right_rectified": right_rectified,
            "left_matched": left_matched,
            "right_matched": right_matched,
            "disparity": disparity,
            "depth_m": depth_m,
            "disparity_vis": vis,
        }

    def _load_stereo_yaml(self) -> dict[str, Any]:
        model = self.config["calibration"]["model"]
        path = self.output_dir / f"stereo_{model}.yaml"
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def _build_matchers(self):
        num_disparities = int(self.matcher_cfg["num_disparities"])
        if num_disparities % 16 != 0:
            raise ValueError("matcher.num_disparities must be divisible by 16")
        block_size = int(self.matcher_cfg["block_size"])
        p1 = int(self.matcher_cfg["p1_scale"]) * 3 * block_size * block_size
        p2 = int(self.matcher_cfg["p2_scale"]) * 3 * block_size * block_size
        mode_name = str(self.matcher_cfg.get("mode", "sgbm_3way")).lower()
        mode = cv2.STEREO_SGBM_MODE_SGBM_3WAY if mode_name == "sgbm_3way" else cv2.STEREO_SGBM_MODE_SGBM
        left_matcher = cv2.StereoSGBM_create(
            minDisparity=int(self.matcher_cfg["min_disparity"]),
            numDisparities=num_disparities,
            blockSize=block_size,
            P1=p1,
            P2=p2,
            disp12MaxDiff=int(self.matcher_cfg["disp12_max_diff"]),
            uniquenessRatio=int(self.matcher_cfg["uniqueness_ratio"]),
            speckleWindowSize=int(self.matcher_cfg["speckle_window_size"]),
            speckleRange=int(self.matcher_cfg["speckle_range"]),
            preFilterCap=int(self.matcher_cfg["pre_filter_cap"]),
            mode=mode,
        )
        right_matcher = cv2.ximgproc.createRightMatcher(left_matcher)
        return left_matcher, right_matcher

    def _build_wls_filter(self):
        if not hasattr(cv2, "ximgproc"):
            return None
        wls_filter = cv2.ximgproc.createDisparityWLSFilter(self.left_matcher)
        wls_filter.setLambda(float(self.matcher_cfg.get("wls_lambda", 8000.0)))
        wls_filter.setSigmaColor(float(self.matcher_cfg.get("wls_sigma", 1.5)))
        return wls_filter

    @staticmethod
    def _colorize_disparity(disparity: np.ndarray) -> np.ndarray:
        finite_mask = np.isfinite(disparity)
        if not finite_mask.any():
            return np.zeros((disparity.shape[0], disparity.shape[1], 3), dtype=np.uint8)
        valid = disparity[finite_mask]
        lo = float(np.nanpercentile(valid, 5.0))
        hi = float(np.nanpercentile(valid, 95.0))
        if hi <= lo:
            hi = lo + 1.0
        normalized = np.clip((disparity - lo) / (hi - lo), 0.0, 1.0)
        normalized[~finite_mask] = 0.0
        img = (normalized * 255.0).astype(np.uint8)
        return cv2.applyColorMap(img, cv2.COLORMAP_TURBO)
