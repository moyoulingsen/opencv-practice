# Runtime Rectification Guide

This guide combines the current best stereo calibration parameters with the recommended runtime rectification workflow.

## Recommended Calibration Result

Use this calibration directory:

- `stereo_vision/data/outputs_camera_roll_33_simple_joint`

This result was built from `33` combined raw images split from `2560 x 720` into per-eye `1280 x 720` frames.

### RMS And Baseline

- Left mono RMS: `0.16611880876014082`
- Right mono RMS: `0.17910094517033096`
- Stereo RMS: `0.34315087467613176`
- Baseline: `0.06455155774717454 m`

### Left Intrinsics

- `fx = 722.2447115157534`
- `fy = 722.7085917219384`
- `cx = 659.2674746559226`
- `cy = 434.6382335717472`
- Distortion (`k1 k2 p1 p2 k3`):
  - `0.07885512300315255`
  - `-0.03399762548214414`
  - `0.001539055973704068`
  - `-0.0006619068899996066`
  - `-0.11214761163554972`

### Right Intrinsics

- `fx = 733.9383641002383`
- `fy = 734.4323670766288`
- `cx = 663.4379236953868`
- `cy = 404.8508751425044`
- Distortion (`k1 k2 p1 p2 k3`):
  - `0.08544795702353387`
  - `-0.06588909230409165`
  - `-0.000634450498064422`
  - `-0.0005120732389506823`
  - `-0.0759081768307854`

### Stereo Extrinsics

Rotation `R`:

```text
[ 0.999921667956878,    0.00037752934462032515,  0.012510612372261856]
[-0.00045036784792996877, 0.9999829632194691,    0.00581983157930506]
[-0.012508202074502628,  -0.005825010077577209,  0.9999048025379513]
```

Translation `T` in meters:

```text
[-0.06424183231546104, 0.0005079215282347282, 0.006295443118649419]
```

## Runtime Rectification Strategy

### Input And Output Size

- Raw combined UVC frame: `2560 x 720`
- Split left eye: `1280 x 720`
- Split right eye: `1280 x 720`
- Rectified left eye: `1280 x 720`
- Rectified right eye: `1280 x 720`
- If you concatenate rectified left and right for preview, the combined preview is `2560 x 720`

So rectification does not change the per-eye pixel count. It changes the geometric mapping inside the same `1280 x 720` canvas.

### Recommended Runtime Rectification Settings

- Rectification source: `stereo_vision/data/outputs_camera_roll_33_simple_joint/stereo_pinhole.yaml`
- Recommended `alpha`: `0.20`
- Recommended mode: centered principal point

This combination preserves more of the lower-left content than the raw OpenCV projection-center placement while avoiding the heavy cropping of `alpha=0.0`.

## Real-Time Script

Use this script:

- `stereo_vision/scripts/run_rectify_live.py`

### Live Rectification Command

```bash
conda activate stereo_cv
cd F:\learning_dl\stereo_vision
python scripts/run_rectify_live.py --config configs/default.yaml --stereo-dir data/outputs_camera_roll_33_simple_joint --alpha 0.20
```

Default behavior:

- Uses the combined UVC source from `configs/default.yaml`
- Uses centered principal point mode
- Displays the rectified stereo pair live
- Press `s` to save a rectified snapshot
- Press `Esc` to quit

### Other Useful Views

```bash
python scripts/run_rectify_live.py --config configs/default.yaml --stereo-dir data/outputs_camera_roll_33_simple_joint --alpha 0.20 --view compare
python scripts/run_rectify_live.py --config configs/default.yaml --stereo-dir data/outputs_camera_roll_33_simple_joint --alpha 0.20 --view left
python scripts/run_rectify_live.py --config configs/default.yaml --stereo-dir data/outputs_camera_roll_33_simple_joint --alpha 0.20 --view right
```

### Disable Centered Principal Point

```bash
python scripts/run_rectify_live.py --config configs/default.yaml --stereo-dir data/outputs_camera_roll_33_simple_joint --alpha 0.20 --native-principal-point
```

### File Test Mode

```bash
python scripts/run_rectify_live.py --config configs/default.yaml --stereo-dir data/outputs_camera_roll_33_simple_joint --alpha 0.20 --left-file data/camera_roll_33_clean/left/pair_0001.png --right-file data/camera_roll_33_clean/right/pair_0001.png
```

This writes rectified outputs into:

- `stereo_vision/data/runtime_rectified_captures`

## How The Transformation Works

At startup the script does this once:

1. Load `K1`, `D1`, `K2`, `D2`, `R`, and `T`
2. Call `cv2.stereoRectify(...)` with your chosen `alpha`
3. Optionally shift the rectified principal point to the image center
4. Build `initUndistortRectifyMap(...)` for left and right

At runtime it does this per frame:

1. Read one combined `2560 x 720` UVC frame
2. Split it into two `1280 x 720` images
3. Apply `cv2.remap(...)` to left and right
4. Display or save the rectified result

## RK3588 Deployment Notes

Real-time rectification is practical on RK3588 because runtime work is only two remaps per frame after the maps are precomputed.

Recommended deployment path:

- Prototype in Python first
- For low latency deployment, move to C++ if needed
- Precompute maps at startup, never per frame
- Use `cv::convertMaps` to get faster fixed-point maps if needed
- Keep camera input in `1280 x 720` per eye if latency matters

The heavy part is usually stereo matching, not rectification itself.
