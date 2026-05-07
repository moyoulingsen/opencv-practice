#!/usr/bin/env bash

set -eo pipefail

# Stop any existing RViz instance before relaunching.
killall rviz2 2>/dev/null || true
sleep 1

# Keep the full set of rendering-related knobs from the known-good script.
export __GL_SYNC_TO_VBLANK=1
export __GL_THREADED_OPTIMIZATIONS=0
export OGRE_RENDER_SYSTEM=GL3+
export vblank_mode=0
export __GL_YIELD=USLEEP
export OGRE_MAX_FRAME_RATE=60
export OGRE_MIN_FRAME_RATE=30
export QT_QUICK_BACKEND=software
export QT_AUTO_SCREEN_SCALE_FACTOR=0

# Clear RViz/OGRE cache to avoid stale rendering state.
rm -rf "${HOME}/.cache/rviz2" "${HOME}/.cache/OGRE"

exec rviz2 "$@"
