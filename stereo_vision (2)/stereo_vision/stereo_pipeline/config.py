from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_config(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    return _normalize_paths(config, path.parent)


def _normalize_paths(config: dict[str, Any], config_dir: Path) -> dict[str, Any]:
    path_keys = {
        "calibration_left_dir",
        "calibration_right_dir",
        "runtime_left_dir",
        "runtime_right_dir",
        "output_dir",
    }
    paths = config.get("paths", {})
    normalized: dict[str, str] = {}
    for key, value in paths.items():
        if key in path_keys:
            normalized[key] = str((config_dir.parent / value).resolve())
        else:
            normalized[key] = value
    config["paths"] = normalized
    return config
