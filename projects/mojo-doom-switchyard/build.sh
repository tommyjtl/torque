#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")"
tool_root="${MOJO_LAB:-../mojo-exploration}"
mojo="${MOJO:-$tool_root/.host-venv/bin/mojo}"
zig="${ZIG:-$tool_root/.toolchains/zig-aarch64-macos-0.17.1/zig}"
sdl_include="${SDL2_INCLUDE:-$(sdl2-config --prefix)/include/SDL2}"
mkdir -p build
case "${1:-host}" in
host)
    "$mojo" build src/engine.mojo --emit object -o build/engine-host.o
    cc -O2 -std=gnu11 -Wall -Wextra -Werror -Wno-deprecated-declarations -DGL_GLEXT_PROTOTYPES -I"$sdl_include" src/platform.c build/engine-host.o -lm -o build/switchyard
    ;;
unoq)
    "$mojo" build src/engine.mojo --target-triple aarch64-unknown-linux-gnu --target-cpu cortex-a53 --emit object -o build/engine-unoq.o
    "$zig" cc -target aarch64-linux-gnu.2.34 -mcpu=cortex_a53 -std=gnu11 -O2 -Wall -Wextra -Werror -DGL_GLEXT_PROTOTYPES -I"$sdl_include" src/platform.c build/engine-unoq.o -ldl -lm -o build/switchyard-unoq
    ;;
*) echo 'Usage: build.sh host|unoq' >&2; exit 64 ;;
esac
