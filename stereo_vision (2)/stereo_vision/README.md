# Stereo Vision Pipeline

Python/OpenCV stereo calibration and depth pipeline for a `6x8` inner-corner checkerboard with measured `25 mm` squares.

## Project Layout

- `configs/default.yaml`: camera, board, and matcher settings.
- `stereo_pipeline/`: reusable calibration and depth modules.
- `scripts/capture_pairs.py`: capture stereo image pairs from a combined UVC frame or two separate cameras.
- `scripts/calibrate_stereo.py`: run mono + stereo calibration and save outputs.
- `scripts/run_depth.py`: rectify images and compute disparity/depth from files or live cameras.
- `scripts/evaluate_depth.py`: inspect disparity/depth statistics inside an ROI.

## Conda Environment

The environment is created at `D:\conda_venv\stereo_cv`.

```bash
conda activate stereo_cv
```

If activation is unavailable in your shell, call the interpreter directly:

```bash
"D:\conda_venv\stereo_cv\python.exe" scripts/calibrate_stereo.py --config configs/default.yaml
```

## Data Layout

Place stereo images in matching order:

```text
data/
  calibration/
    left/
      0001.png
      0002.png
    right/
      0001.png
      0002.png
  runtime/
    left/
    right/
  outputs/
```

## Typical Workflow

1. Capture 30-40 stereo pairs with broad pose coverage.

```bash
python scripts/capture_pairs.py --config configs/default.yaml
```

Defaults now match your UVC camera:

- device: `1`
- input mode: one combined frame split as left/right
- combined resolution: `2560x720`
- per-eye calibration resolution: `1280x720`
- timed auto capture: every `5` seconds
- target count: `36` stereo pairs
- save only when the checkerboard is found in both halves

Useful overrides:

```bash
python scripts/capture_pairs.py --config configs/default.yaml --interval 1 --target-pairs 40
python scripts/capture_pairs.py --config configs/default.yaml --interval 5 --target-pairs 36
python scripts/capture_pairs.py --config configs/default.yaml --manual
```

2. Run calibration:
```bash
python scripts/calibrate_stereo.py --config configs/default.yaml
```

3. Run depth on saved or live frames:

```bash
python scripts/run_depth.py --config configs/default.yaml --source files
python scripts/run_depth.py --config configs/default.yaml --source live
```

4. Evaluate a known-distance target with an ROI:

```bash
python scripts/evaluate_depth.py --config configs/default.yaml --left data/runtime/left/test.png --right data/runtime/right/test.png --roi 420 220 220 180
```

## Calibration Outputs

Outputs are written under `data/outputs/`:

- `mono_left.yaml`
- `mono_right.yaml`
- `stereo_pinhole.yaml` or `stereo_fisheye.yaml`
- `rectification_maps.npz`
- `calibration_report.yaml`

## Model Choice

`configs/default.yaml` now defaults to `pinhole`, which matches your current preference for a moderate wide-angle lens.

## Automatic Filtering

Calibration now filters weak samples before solving stereo parameters.

- Rejects blurry pairs using Laplacian sharpness.
- Rejects boards that are too small, too large, or too close to the image border.
- Rejects near-duplicate poses so the dataset keeps better geometric diversity.
- Can iteratively remove samples that pull the solved baseline away from the expected `6.5 cm` target.
- Writes accepted and rejected sample details to `data/outputs/calibration_report.yaml`.

Main tuning knobs are under `calibration.filter` in `configs/default.yaml`.

## How To Hold The Checkerboard

Aim for `30-40` valid pairs, not just many nearly identical images.

- Keep the board flat, fully visible, and sharp in both left and right halves.
- Start with `8-10` front-facing frames at different distances: about `0.25 m`, `0.35 m`, `0.5 m`, `0.8 m`, `1.2 m`.
- Add `10-12` tilted frames: pitch up/down and yaw left/right around `15-45 deg`.
- Add `8-10` off-center frames: move the board into each corner and along each edge.
- Add `4-8` rotated frames: roll the board clockwise and counterclockwise while staying visible.
- Avoid blur, glare, strong shadows, and poses where the board touches the image border.

A practical capture sequence:

1. Center near, center mid, center far.
2. Top-left, top-right, bottom-left, bottom-right.
3. Left tilt, right tilt, up tilt, down tilt.
4. Stronger tilts at near and mid distance.
5. A few rolled poses around `15-30 deg`.

If auto capture is set to `2` seconds, move the board to a new pose after each successful save. Wait until the preview text shows the board was detected on both sides before holding still for the next shot.
