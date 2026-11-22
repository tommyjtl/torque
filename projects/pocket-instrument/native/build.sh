#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
tool_root=../../mojo-exploration
mojo="${MOJO:-$tool_root/.host-venv/bin/mojo}"
zig="${ZIG:-$tool_root/.toolchains/zig-aarch64-macos-0.17.1/zig}"
sdl_headers="${SDL2_INCLUDE:-$(sdl2-config --prefix)/include/SDL2}"
mkdir -p build
test -s build/skin.h || node prepare.cjs
if [[ ! -s build/inspect.mesh || ../inspect-model.mjs -nt build/inspect.mesh || bake-model.cjs -nt build/inspect.mesh || ../assets/inspect/layout.json -nt build/inspect.mesh || ../assets/inspect/silkscreen.png -nt build/inspect.mesh ]]; then node bake-model.cjs; fi
: "${GLES_TARGET_LIB:?Point GLES_TARGET_LIB at a copy of the target libGLESv2.so.2}"
: "${SDL2_TARGET_LIB:?Point SDL2_TARGET_LIB at a copy of the target board SDL2 shared library}"
"$mojo" build engine.mojo --target-triple aarch64-unknown-linux-gnu --target-cpu cortex-a53 --emit object -o build/engine.o
"$zig" cc -target aarch64-linux-gnu.2.34 -mcpu=cortex_a53 -std=gnu11 -O2 -Wall -Wextra -Werror -I"$sdl_headers" platform.c inspection.c build/engine.o "$SDL2_TARGET_LIB" "$GLES_TARGET_LIB" -lm -o build/bap

mkdir -p build/package
cp build/bap build/inspect.mesh build/face.bmp build/comic?.bmp build/font.rgba build/factory.f32 \
  ../assets/SpaceGrotesk-OFL.txt ../assets/DSEG-LICENSE.txt BAP.desktop build/package/
cp ../assets/bap-mark.svg build/package/bap-icon.svg
(
  cd build/package
  shasum -a 256 bap inspect.mesh *.bmp font.rgba factory.f32 bap-icon.svg BAP.desktop *.txt > SHA256SUMS
  COPYFILE_DISABLE=1 tar -czf ../bap-linux-arm64.tgz \
    bap inspect.mesh *.bmp font.rgba factory.f32 bap-icon.svg BAP.desktop *.txt SHA256SUMS
)
