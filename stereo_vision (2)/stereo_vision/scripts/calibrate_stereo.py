from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereo_pipeline.calibration import StereoCalibrationPipeline
from stereo_pipeline.config import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run stereo calibration")
    parser.add_argument("--config", default="configs/default.yaml")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    pipeline = StereoCalibrationPipeline(config)
    report = pipeline.run()
    print("Calibration complete")
    for key, value in report.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
