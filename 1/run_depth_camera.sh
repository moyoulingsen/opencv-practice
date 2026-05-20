#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

if ! python3 -c "import cv2, numpy" >/dev/null 2>&1; then
  echo "Missing Python dependencies. Installing opencv-python and numpy..."
  python3 -m pip install -r requirements.txt
fi

args=()
while (($#)); do
  case "$1" in
    --calib)
      if (($# < 2)); then
        echo "--calib requires a path" >&2
        exit 2
      fi
      if [[ "$2" = /* ]]; then
        calib_path="$2"
      else
        calib_path="$PROJECT_DIR/$2"
      fi
      args+=(--calib "$calib_path")
      shift 2
      ;;
    --calib=*)
      calib_path="${1#--calib=}"
      if [[ "$calib_path" != /* ]]; then
        calib_path="$PROJECT_DIR/$calib_path"
      fi
      args+=(--calib "$calib_path")
      shift
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

python3 mf287_depth_camera.py "${args[@]}"
