from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from .io_utils import ensure_dir, pair_images, read_gray_image, summarize_numeric


@dataclass
class CalibrationSample:
    name: str
    object_points: np.ndarray
    left_corners: np.ndarray
    right_corners: np.ndarray
    left_blur: float
    right_blur: float
    board_area_ratio: float
    border_margin_ratio: float
    center_x_ratio: float
    center_y_ratio: float
    board_width_ratio: float
    board_height_ratio: float
    accepted: bool = True
    rejection_reason: str = ""


class StereoCalibrationPipeline:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        board = config["board"]
        self.board_size = (int(board["cols"]), int(board["rows"]))
        self.square_size_m = float(board["square_size_m"])
        self.model = str(config["calibration"]["model"]).lower()
        self.use_sb = bool(config["calibration"].get("use_find_corners_sb", True))
        self.subpix_window = int(config["calibration"].get("subpix_window", 11))
        self.min_pairs = int(config["calibration"].get("min_pairs", 12))
        self.rectify_alpha = float(config["calibration"].get("rectify_alpha", 0.0))
        self.use_rational_model = bool(config["calibration"].get("use_rational_model", True))
        self.stereo_fix_intrinsics = bool(config["calibration"].get("stereo_fix_intrinsics", True))
        self.expected_image_size = (
            int(config["calibration"].get("expected_image_width", 1280)),
            int(config["calibration"].get("expected_image_height", 720)),
        )
        self.expected_baseline_m = float(config["calibration"].get("expected_baseline_m", 0.065))
        self.fixed_intrinsics = bool(config["calibration"].get("fixed_intrinsics", False))
        self.fixed_left_intrinsics_path = config["calibration"].get("fixed_left_intrinsics_path")
        self.fixed_right_intrinsics_path = config["calibration"].get("fixed_right_intrinsics_path")
        filter_cfg = config["calibration"].get("filter", {})
        self.filter_enabled = bool(filter_cfg.get("enabled", True))
        self.min_laplacian_var = float(filter_cfg.get("min_laplacian_var", 80.0))
        self.min_board_area_ratio = float(filter_cfg.get("min_board_area_ratio", 0.08))
        self.max_board_area_ratio = float(filter_cfg.get("max_board_area_ratio", 0.70))
        self.min_border_margin_ratio = float(filter_cfg.get("min_border_margin_ratio", 0.03))
        self.min_pose_delta = float(filter_cfg.get("min_pose_delta", 0.035))
        refine_cfg = filter_cfg.get("baseline_refine", {})
        self.baseline_refine_enabled = bool(refine_cfg.get("enabled", True))
        self.baseline_refine_max_iterations = int(refine_cfg.get("max_iterations", 8))
        self.baseline_refine_min_improvement = float(refine_cfg.get("min_improvement", 0.03))
        self.stereo_rms_weight = float(refine_cfg.get("stereo_rms_weight", 0.35))
        self.baseline_error_weight = float(refine_cfg.get("baseline_error_weight", 1.0))
        self.output_dir = ensure_dir(config["paths"]["output_dir"])
        self.object_point_template = self._build_object_points()

    def run(self) -> dict[str, Any]:
        pairs = pair_images(
            self.config["paths"]["calibration_left_dir"],
            self.config["paths"]["calibration_right_dir"],
        )
        samples, rejected_samples, image_size = self._collect_samples(pairs)
        if len(samples) < self.min_pairs:
            raise ValueError(
                f"Only {len(samples)} valid pairs found. Need at least {self.min_pairs}."
            )

        samples, secondary_rejected = self._refine_samples_by_stereo_objective(samples, image_size)
        rejected_samples.extend(secondary_rejected)
        if len(samples) < self.min_pairs:
            raise ValueError(
                f"Only {len(samples)} pairs remain after stereo refinement. Need at least {self.min_pairs}."
            )

        left_result, right_result, stereo_result = self._solve_calibration(samples, image_size)
        self._save_outputs(
            left_result,
            right_result,
            stereo_result,
            image_size,
            samples,
            rejected_samples,
        )

        baseline_m = float(np.linalg.norm(stereo_result["T"]))
        return {
            "model": self.model,
            "image_size": image_size,
            "valid_pairs": len(samples),
            "rejected_pairs": len(rejected_samples),
            "left_rms": float(left_result["rms"]),
            "right_rms": float(right_result["rms"]),
            "stereo_rms": float(stereo_result["rms"]),
            "baseline_m": baseline_m,
        }

    def _solve_calibration(
        self,
        samples: list[CalibrationSample],
        image_size: tuple[int, int],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        object_points = [sample.object_points for sample in samples]
        left_points = [sample.left_corners for sample in samples]
        right_points = [sample.right_corners for sample in samples]
        if self.fixed_intrinsics:
            left_result = self._load_intrinsics_result(self.fixed_left_intrinsics_path, image_size)
            right_result = self._load_intrinsics_result(self.fixed_right_intrinsics_path, image_size)
        else:
            left_result = self._calibrate_single(object_points, left_points, image_size)
            right_result = self._calibrate_single(object_points, right_points, image_size)
        stereo_result = self._calibrate_stereo(
            object_points,
            left_points,
            right_points,
            image_size,
            left_result,
            right_result,
        )
        return left_result, right_result, stereo_result

    def _load_intrinsics_result(
        self,
        intrinsics_path: str | None,
        image_size: tuple[int, int],
    ) -> dict[str, Any]:
        if not intrinsics_path:
            raise ValueError("Fixed intrinsics enabled but intrinsics path is missing.")
        path = Path(intrinsics_path)
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        file_size = (int(data["image_width"]), int(data["image_height"]))
        if file_size != image_size:
            raise ValueError(
                f"Fixed intrinsics size mismatch for {path}: got {file_size}, expected {image_size}."
            )
        K = np.asarray(data["camera_matrix"], dtype=np.float64)
        D = np.asarray(data["dist_coeffs"], dtype=np.float64).reshape(-1, 1)
        return {"rms": float(data.get("rms", 0.0)), "K": K, "D": D, "rvecs": [], "tvecs": []}

    def _build_object_points(self) -> np.ndarray:
        cols, rows = self.board_size
        grid = np.zeros((rows * cols, 1, 3), dtype=np.float64)
        xy = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
        grid[:, 0, :2] = xy * self.square_size_m
        return grid

    def _collect_samples(
        self, pairs: list[tuple[Path, Path]]
    ) -> tuple[list[CalibrationSample], list[CalibrationSample], tuple[int, int]]:
        candidates: list[CalibrationSample] = []
        rejected: list[CalibrationSample] = []
        image_size: tuple[int, int] | None = None
        for left_path, right_path in pairs:
            left_gray = read_gray_image(left_path)
            right_gray = read_gray_image(right_path)
            if left_gray.shape != right_gray.shape:
                raise ValueError(
                    f"Stereo pair shape mismatch: {left_path.name} vs {right_path.name}"
                )
            if image_size is None:
                image_size = (left_gray.shape[1], left_gray.shape[0])
                if image_size != self.expected_image_size:
                    raise ValueError(
                        "Calibration images have unexpected size: "
                        f"got {image_size[0]}x{image_size[1]}, "
                        f"expected {self.expected_image_size[0]}x{self.expected_image_size[1]}."
                    )
            left_corners = self._detect_corners(left_gray)
            right_corners = self._detect_corners(right_gray)
            if left_corners is None or right_corners is None:
                continue
            left_corners, right_corners = self._normalize_stereo_corner_order(
                left_corners,
                right_corners,
            )
            sample = CalibrationSample(
                name=left_path.stem,
                object_points=self.object_point_template.copy(),
                left_corners=left_corners,
                right_corners=right_corners,
                left_blur=self._compute_blur(left_gray),
                right_blur=self._compute_blur(right_gray),
                board_area_ratio=0.0,
                border_margin_ratio=0.0,
                center_x_ratio=0.0,
                center_y_ratio=0.0,
                board_width_ratio=0.0,
                board_height_ratio=0.0,
            )
            self._populate_geometry_metrics(sample, image_size)
            candidates.append(sample)
        if image_size is None:
            raise ValueError("No readable calibration images found.")
        accepted, auto_rejected = self._filter_samples(candidates)
        rejected.extend(auto_rejected)
        return accepted, rejected, image_size

    @staticmethod
    def _compute_blur(gray: np.ndarray) -> float:
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def _populate_geometry_metrics(
        self,
        sample: CalibrationSample,
        image_size: tuple[int, int],
    ) -> None:
        width, height = image_size
        corners = np.vstack([sample.left_corners.reshape(-1, 2), sample.right_corners.reshape(-1, 2)])
        min_xy = corners.min(axis=0)
        max_xy = corners.max(axis=0)
        board_width = float(max_xy[0] - min_xy[0])
        board_height = float(max_xy[1] - min_xy[1])
        area_ratio = (board_width * board_height) / float(width * height)
        margin = min(min_xy[0], min_xy[1], width - max_xy[0], height - max_xy[1])
        center = corners.mean(axis=0)
        sample.board_area_ratio = float(area_ratio)
        sample.border_margin_ratio = float(margin / min(width, height))
        sample.center_x_ratio = float(center[0] / width)
        sample.center_y_ratio = float(center[1] / height)
        sample.board_width_ratio = float(board_width / width)
        sample.board_height_ratio = float(board_height / height)

    def _filter_samples(
        self,
        candidates: list[CalibrationSample],
    ) -> tuple[list[CalibrationSample], list[CalibrationSample]]:
        if not self.filter_enabled:
            return candidates, []

        accepted: list[CalibrationSample] = []
        rejected: list[CalibrationSample] = []
        candidates = sorted(candidates, key=self._sample_priority, reverse=True)
        for sample in candidates:
            reason = self._evaluate_sample_rejection(sample, accepted)
            if reason is None:
                accepted.append(sample)
            else:
                sample.accepted = False
                sample.rejection_reason = reason
                rejected.append(sample)

        if len(accepted) < self.min_pairs:
            fallback = sorted(candidates, key=self._sample_priority, reverse=True)
            keep_count = min(len(fallback), max(self.min_pairs, len(accepted)))
            accepted = fallback[:keep_count]
            accepted_names = {sample.name for sample in accepted}
            rejected = []
            for sample in candidates:
                if sample.name not in accepted_names:
                    sample.accepted = False
                    if not sample.rejection_reason:
                        sample.rejection_reason = "not selected by fallback ranking"
                    rejected.append(sample)
                else:
                    sample.accepted = True
                    sample.rejection_reason = ""
        accepted.sort(key=lambda item: item.name)
        rejected.sort(key=lambda item: item.name)
        return accepted, rejected

    def _refine_samples_by_stereo_objective(
        self,
        samples: list[CalibrationSample],
        image_size: tuple[int, int],
    ) -> tuple[list[CalibrationSample], list[CalibrationSample]]:
        if not self.filter_enabled or not self.baseline_refine_enabled:
            return samples, []
        if len(samples) <= self.min_pairs:
            return samples, []

        current = list(samples)
        rejected: list[CalibrationSample] = []
        current_score = self._evaluate_stereo_score(current, image_size)
        iterations = 0

        while len(current) > self.min_pairs and iterations < self.baseline_refine_max_iterations:
            best_index = -1
            best_score = current_score
            for idx in range(len(current)):
                candidate = current[:idx] + current[idx + 1 :]
                if len(candidate) < self.min_pairs:
                    continue
                score = self._evaluate_stereo_score(candidate, image_size)
                if score < best_score:
                    best_score = score
                    best_index = idx
            if best_index < 0:
                break
            improvement = current_score - best_score
            if improvement < self.baseline_refine_min_improvement:
                break
            removed = current.pop(best_index)
            removed.accepted = False
            removed.rejection_reason = "removed by baseline refinement"
            rejected.append(removed)
            current_score = best_score
            iterations += 1

        current.sort(key=lambda item: item.name)
        rejected.sort(key=lambda item: item.name)
        return current, rejected

    def _evaluate_stereo_score(
        self,
        samples: list[CalibrationSample],
        image_size: tuple[int, int],
    ) -> float:
        try:
            _, _, stereo_result = self._solve_calibration(samples, image_size)
        except cv2.error:
            return float("inf")
        stereo_rms = float(stereo_result["rms"])
        baseline_error_ratio = abs(float(np.linalg.norm(stereo_result["T"])) - self.expected_baseline_m)
        baseline_error_ratio /= max(self.expected_baseline_m, 1e-6)
        return self.stereo_rms_weight * stereo_rms + self.baseline_error_weight * baseline_error_ratio

    def _sample_priority(self, sample: CalibrationSample) -> tuple[float, float, float]:
        return (
            min(sample.left_blur, sample.right_blur),
            sample.board_area_ratio,
            sample.border_margin_ratio,
        )

    def _evaluate_sample_rejection(
        self,
        sample: CalibrationSample,
        accepted: list[CalibrationSample],
    ) -> str | None:
        if min(sample.left_blur, sample.right_blur) < self.min_laplacian_var:
            return "blur below threshold"
        if sample.board_area_ratio < self.min_board_area_ratio:
            return "checkerboard too small"
        if sample.board_area_ratio > self.max_board_area_ratio:
            return "checkerboard too large"
        if sample.border_margin_ratio < self.min_border_margin_ratio:
            return "checkerboard too close to border"
        if accepted:
            nearest_pose_delta = min(self._pose_delta(sample, ref) for ref in accepted)
            if nearest_pose_delta < self.min_pose_delta:
                return "pose too similar to existing sample"
        return None

    @staticmethod
    def _pose_delta(sample: CalibrationSample, reference: CalibrationSample) -> float:
        delta = np.array(
            [
                sample.center_x_ratio - reference.center_x_ratio,
                sample.center_y_ratio - reference.center_y_ratio,
                sample.board_width_ratio - reference.board_width_ratio,
                sample.board_height_ratio - reference.board_height_ratio,
            ],
            dtype=np.float64,
        )
        return float(np.linalg.norm(delta))

    def _detect_corners(self, gray: np.ndarray) -> np.ndarray | None:
        flags = cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY
        found = False
        corners = None
        if self.use_sb:
            found, corners = cv2.findChessboardCornersSB(gray, self.board_size, flags=flags)
        if not found:
            legacy_flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
            found, corners = cv2.findChessboardCorners(gray, self.board_size, legacy_flags)
        if not found or corners is None:
            return None
        criteria = (
            cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
            50,
            1e-4,
        )
        refined = cv2.cornerSubPix(
            gray,
            corners,
            (self.subpix_window, self.subpix_window),
            (-1, -1),
            criteria,
        )
        return refined.astype(np.float64)

    def _corner_order_candidates(self, corners: np.ndarray) -> list[np.ndarray]:
        cols, rows = self.board_size
        grid = corners.reshape(rows, cols, 1, 2)
        candidates = [
            grid,
            grid[::-1, ::-1],
            grid[:, ::-1],
            grid[::-1, :],
        ]
        return [candidate.reshape(-1, 1, 2) for candidate in candidates]

    def _normalize_corner_order(self, corners: np.ndarray) -> np.ndarray:
        cols, rows = self.board_size
        candidates = [candidate.reshape(rows, cols, 1, 2) for candidate in self._corner_order_candidates(corners)]

        def score(candidate: np.ndarray) -> tuple[int, float, float]:
            points = candidate.reshape(rows, cols, 2)
            mean_dx = float(np.mean(np.diff(points[:, :, 0], axis=1)))
            mean_dy = float(np.mean(np.diff(points[:, :, 1], axis=0)))
            first = points[0, 0]
            penalty = 0
            if mean_dx <= 0:
                penalty += 10
            if mean_dy <= 0:
                penalty += 10
            return (penalty, float(first[0] + first[1]), -mean_dx - mean_dy)

        best = min(candidates, key=score)
        return best.reshape(-1, 1, 2)

    def _normalize_stereo_corner_order(
        self,
        left_corners: np.ndarray,
        right_corners: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        left_candidates = self._corner_order_candidates(left_corners)
        right_candidates = self._corner_order_candidates(right_corners)

        def pair_score(left_candidate: np.ndarray, right_candidate: np.ndarray) -> tuple[float, float, float, float]:
            left_pts = left_candidate.reshape(-1, 2)
            right_pts = right_candidate.reshape(-1, 2)
            disparity = left_pts[:, 0] - right_pts[:, 0]
            vertical = left_pts[:, 1] - right_pts[:, 1]
            sign_penalty = 0.0 if float(np.mean(disparity)) > 0.0 else 1000.0
            return (
                sign_penalty + float(np.mean(np.abs(vertical))),
                float(np.std(vertical)),
                float(np.std(disparity)),
                -float(np.mean(disparity)),
            )

        best_left = self._normalize_corner_order(left_corners)
        best_right = self._normalize_corner_order(right_corners)
        best_score = pair_score(best_left, best_right)
        for left_candidate in left_candidates:
            for right_candidate in right_candidates:
                score = pair_score(left_candidate, right_candidate)
                if score < best_score:
                    best_left = left_candidate
                    best_right = right_candidate
                    best_score = score
        return best_left, best_right

    def _calibrate_single(
        self,
        object_points: list[np.ndarray],
        image_points: list[np.ndarray],
        image_size: tuple[int, int],
    ) -> dict[str, Any]:
        if self.model == "fisheye":
            K = np.eye(3, dtype=np.float64)
            D = np.zeros((4, 1), dtype=np.float64)
            flags = (
                cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC
                | cv2.fisheye.CALIB_CHECK_COND
                | cv2.fisheye.CALIB_FIX_SKEW
            )
            criteria = (
                cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
                100,
                1e-6,
            )
            rms, K, D, rvecs, tvecs = cv2.fisheye.calibrate(
                object_points,
                image_points,
                image_size,
                K,
                D,
                None,
                None,
                flags,
                criteria,
            )
        elif self.model == "pinhole":
            object_points = [points.reshape(-1, 3).astype(np.float32) for points in object_points]
            image_points = [points.reshape(-1, 2).astype(np.float32) for points in image_points]
            flags = cv2.CALIB_RATIONAL_MODEL if self.use_rational_model else 0
            criteria = (
                cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
                100,
                1e-6,
            )
            rms, K, D, rvecs, tvecs = cv2.calibrateCamera(
                object_points,
                image_points,
                image_size,
                None,
                None,
                flags=flags,
                criteria=criteria,
            )
        else:
            raise ValueError(f"Unsupported calibration model: {self.model}")
        return {"rms": rms, "K": K, "D": D, "rvecs": rvecs, "tvecs": tvecs}

    def _calibrate_stereo(
        self,
        object_points: list[np.ndarray],
        left_points: list[np.ndarray],
        right_points: list[np.ndarray],
        image_size: tuple[int, int],
        left_result: dict[str, Any],
        right_result: dict[str, Any],
    ) -> dict[str, Any]:
        if self.model == "fisheye":
            flags = cv2.fisheye.CALIB_FIX_INTRINSIC
            criteria = (
                cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
                100,
                1e-6,
            )
            rms, K1, D1, K2, D2, R, T = cv2.fisheye.stereoCalibrate(
                object_points,
                left_points,
                right_points,
                left_result["K"],
                left_result["D"],
                right_result["K"],
                right_result["D"],
                image_size,
                None,
                None,
                flags,
                criteria,
            )
            R1, R2, P1, P2, Q = cv2.fisheye.stereoRectify(
                K1,
                D1,
                K2,
                D2,
                image_size,
                R,
                T,
                flags=cv2.CALIB_ZERO_DISPARITY,
                balance=self.rectify_alpha,
                fov_scale=1.0,
            )
        else:
            object_points = [points.reshape(-1, 3).astype(np.float32) for points in object_points]
            left_points = [points.reshape(-1, 2).astype(np.float32) for points in left_points]
            right_points = [points.reshape(-1, 2).astype(np.float32) for points in right_points]
            flags = cv2.CALIB_FIX_INTRINSIC if self.stereo_fix_intrinsics else 0
            criteria = (
                cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
                100,
                1e-6,
            )
            rms, K1, D1, K2, D2, R, T, E, F = cv2.stereoCalibrate(
                object_points,
                left_points,
                right_points,
                left_result["K"],
                left_result["D"],
                right_result["K"],
                right_result["D"],
                image_size,
                criteria=criteria,
                flags=flags,
            )
            R1, R2, P1, P2, Q, _, _ = cv2.stereoRectify(
                K1,
                D1,
                K2,
                D2,
                image_size,
                R,
                T,
                alpha=self.rectify_alpha,
            )
        left_map = self._init_undistort_map(K1, D1, R1, P1, image_size)
        right_map = self._init_undistort_map(K2, D2, R2, P2, image_size)
        return {
            "rms": rms,
            "K1": K1,
            "D1": D1,
            "K2": K2,
            "D2": D2,
            "R": R,
            "T": T,
            "R1": R1,
            "R2": R2,
            "P1": P1,
            "P2": P2,
            "Q": Q,
            "left_map": left_map,
            "right_map": right_map,
        }

    def _init_undistort_map(
        self,
        K: np.ndarray,
        D: np.ndarray,
        R: np.ndarray,
        P: np.ndarray,
        image_size: tuple[int, int],
    ) -> tuple[np.ndarray, np.ndarray]:
        if self.model == "fisheye":
            map1, map2 = cv2.fisheye.initUndistortRectifyMap(
                K, D, R, P, image_size, cv2.CV_32FC1
            )
        else:
            map1, map2 = cv2.initUndistortRectifyMap(
                K, D, R, P, image_size, cv2.CV_32FC1
            )
        return map1, map2

    def _save_outputs(
        self,
        left_result: dict[str, Any],
        right_result: dict[str, Any],
        stereo_result: dict[str, Any],
        image_size: tuple[int, int],
        samples: list[CalibrationSample],
        rejected_samples: list[CalibrationSample],
    ) -> None:
        self._write_yaml(self.output_dir / "mono_left.yaml", {
            "model": self.model,
            "image_width": image_size[0],
            "image_height": image_size[1],
            "rms": float(left_result["rms"]),
            "camera_matrix": left_result["K"].tolist(),
            "dist_coeffs": np.asarray(left_result["D"]).reshape(-1).tolist(),
        })
        self._write_yaml(self.output_dir / "mono_right.yaml", {
            "model": self.model,
            "image_width": image_size[0],
            "image_height": image_size[1],
            "rms": float(right_result["rms"]),
            "camera_matrix": right_result["K"].tolist(),
            "dist_coeffs": np.asarray(right_result["D"]).reshape(-1).tolist(),
        })
        self._write_yaml(self.output_dir / f"stereo_{self.model}.yaml", {
            "model": self.model,
            "image_width": image_size[0],
            "image_height": image_size[1],
            "rms": float(stereo_result["rms"]),
            "baseline_m": float(np.linalg.norm(stereo_result["T"])),
            "K1": stereo_result["K1"].tolist(),
            "D1": np.asarray(stereo_result["D1"]).reshape(-1).tolist(),
            "K2": stereo_result["K2"].tolist(),
            "D2": np.asarray(stereo_result["D2"]).reshape(-1).tolist(),
            "R": stereo_result["R"].tolist(),
            "T": np.asarray(stereo_result["T"]).reshape(-1).tolist(),
            "R1": stereo_result["R1"].tolist(),
            "R2": stereo_result["R2"].tolist(),
            "P1": stereo_result["P1"].tolist(),
            "P2": stereo_result["P2"].tolist(),
            "Q": stereo_result["Q"].tolist(),
        })
        np.savez_compressed(
            self.output_dir / "rectification_maps.npz",
            left_map_x=stereo_result["left_map"][0],
            left_map_y=stereo_result["left_map"][1],
            right_map_x=stereo_result["right_map"][0],
            right_map_y=stereo_result["right_map"][1],
            Q=stereo_result["Q"],
        )
        self._write_yaml(self.output_dir / "calibration_report.yaml", {
            "model": self.model,
            "valid_pair_count": len(samples),
            "rejected_pair_count": len(rejected_samples),
            "used_sample_names": [sample.name for sample in samples],
            "rejected_samples": [
                {
                    "name": sample.name,
                    "reason": sample.rejection_reason,
                    "left_blur": sample.left_blur,
                    "right_blur": sample.right_blur,
                    "board_area_ratio": sample.board_area_ratio,
                    "border_margin_ratio": sample.border_margin_ratio,
                }
                for sample in rejected_samples
            ],
            "left_rms": float(left_result["rms"]),
            "right_rms": float(right_result["rms"]),
            "stereo_rms": float(stereo_result["rms"]),
            "baseline_m": float(np.linalg.norm(stereo_result["T"])),
            "expected_baseline_m": self.expected_baseline_m,
            "baseline_error_m": float(np.linalg.norm(stereo_result["T"]) - self.expected_baseline_m),
            "pair_index_stats": summarize_numeric(list(range(1, len(samples) + 1))),
            "accepted_sample_metrics": {
                "left_blur": summarize_numeric(sample.left_blur for sample in samples),
                "right_blur": summarize_numeric(sample.right_blur for sample in samples),
                "board_area_ratio": summarize_numeric(sample.board_area_ratio for sample in samples),
                "border_margin_ratio": summarize_numeric(sample.border_margin_ratio for sample in samples),
            },
        })

    @staticmethod
    def _write_yaml(path: Path, data: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, sort_keys=False)
