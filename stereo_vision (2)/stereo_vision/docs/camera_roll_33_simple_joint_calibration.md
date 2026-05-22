# Camera Roll 33 Simple Joint Calibration

This document records the currently best stereo calibration result for the Dechuangxin dual-camera module.

## Dataset

- Source folder: `E:\15312\Pictures\Camera Roll`
- Raw combined images used: `33`
- Removed sample: original image index `28` (`WIN_20260416_18_30_43_Pro.jpg`)
- Calibration dataset path: `stereo_vision/data/camera_roll_33_clean`

## Resolution

- Raw combined input resolution: `2560 x 720`
- Split per-eye resolution used for calibration: `1280 x 720`
- Rectified per-eye resolution: `1280 x 720`
- If rectified left/right images are shown side by side, the combined preview becomes `2560 x 720`

So the adjustment does not change the per-eye pixel size. Calibration and rectification are still performed on `1280 x 720` left/right images split from the original `2560 x 720` frame.

## Calibration Settings

- Model: `pinhole`
- `use_rational_model: false`
- `stereo_fix_intrinsics: false`
- `fixed_intrinsics: false`

## RMS And Baseline

- Left mono RMS: `0.16611880876014082`
- Right mono RMS: `0.17910094517033096`
- Stereo RMS: `0.34315087467613176`
- Baseline: `0.06455155774717454 m`
- Expected baseline: `0.065 m`
- Baseline error: `-0.00044844225282546224 m`

## Left Camera Intrinsics

- Image size: `1280 x 720`
- `fx = 722.2447115157534`
- `fy = 722.7085917219384`
- `cx = 659.2674746559226`
- `cy = 434.6382335717472`
- Distortion (`k1 k2 p1 p2 k3`):
  - `k1 = 0.07885512300315255`
  - `k2 = -0.03399762548214414`
  - `p1 = 0.001539055973704068`
  - `p2 = -0.0006619068899996066`
  - `k3 = -0.11214761163554972`

Camera matrix:

```text
[722.2447115157534,   0.0,               659.2674746559226]
[  0.0,               722.7085917219384, 434.6382335717472]
[  0.0,                 0.0,               1.0]
```

## Right Camera Intrinsics

- Image size: `1280 x 720`
- `fx = 733.9383641002383`
- `fy = 734.4323670766288`
- `cx = 663.4379236953868`
- `cy = 404.8508751425044`
- Distortion (`k1 k2 p1 p2 k3`):
  - `k1 = 0.08544795702353387`
  - `k2 = -0.06588909230409165`
  - `p1 = -0.000634450498064422`
  - `p2 = -0.0005120732389506823`
  - `k3 = -0.0759081768307854`

Camera matrix:

```text
[733.9383641002383,   0.0,               663.4379236953868]
[  0.0,               734.4323670766288, 404.8508751425044]
[  0.0,                 0.0,               1.0]
```

## Stereo Extrinsics

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

Interpretation:

- Main translation is along `X`
- `Tx` is about `-6.42 cm`
- `Ty` is about `0.05 cm`
- `Tz` is about `0.63 cm`

## Rectification Quality

Rectification debug output:

- Report: `stereo_vision/data/rectify_debug_camera_roll_33_simple_joint/rectification_report.yaml`
- Images: `stereo_vision/data/rectify_debug_camera_roll_33_simple_joint`

Key metrics:

- Raw vertical MAE: `24.67192812158604 px`
- Rectified vertical MAE: `0.45375185447049926 px`
- Raw vertical max: `25.12899367014567 px`
- Rectified vertical max: `1.3880009919190164 px`

This indicates the current calibration rectifies the stereo pair well enough for matching.

## High-FOV Rectification Variant

To reduce cropping, an additional rectification export was generated with `rectify_alpha = 1.0`.

- Stereo output: `stereo_vision/data/outputs_camera_roll_33_simple_joint_alpha1`
- Rectification report: `stereo_vision/data/rectify_debug_camera_roll_33_simple_joint_alpha1/rectification_report.yaml`
- Comparison images: `stereo_vision/data/rectify_compare_camera_roll_33_simple_joint_alpha1`

This variant keeps more field of view while preserving good rectification quality:

- Stereo RMS: `0.3434387369314547`
- Baseline: `0.06455158099412696 m`
- Rectified vertical MAE: `0.07086900362467961 px`
- Rectified vertical max: `0.21677771724842052 px`

It is the better choice when preserving viewing angle matters more than aggressive black-border removal.

## Output Files

- Mono left: `stereo_vision/data/outputs_camera_roll_33_simple_joint/mono_left.yaml`
- Mono right: `stereo_vision/data/outputs_camera_roll_33_simple_joint/mono_right.yaml`
- Stereo: `stereo_vision/data/outputs_camera_roll_33_simple_joint/stereo_pinhole.yaml`
- Calibration report: `stereo_vision/data/outputs_camera_roll_33_simple_joint/calibration_report.yaml`
- Rectification maps: `stereo_vision/data/outputs_camera_roll_33_simple_joint/rectification_maps.npz`

## Recommended Working Version

This is the current recommended calibration result to use for depth experiments.
