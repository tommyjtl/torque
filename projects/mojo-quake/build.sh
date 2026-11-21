#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
project=$(pwd)
target=${1:-host}
case "$target" in host|unoq) ;; *) echo "Usage: ./build.sh host|unoq" >&2;exit 64;; esac
lab=${MOJO_LAB:-"$project/../mojo-exploration"}
mojo=${MOJO:-"$lab/.host-venv/bin/mojo"}
zig=${ZIG:-"$lab/.toolchains/zig-aarch64-macos-0.17.1/zig"}
pin=c0553b4ca60b608b68c133faab4f2462f7c5c195
archive="$project/build/tyrquake.tar.gz"
expected=73b6a1925d5078379fb66d7b8cc5678dd38cfd7d27f1c3014f29b2c1005b6f77
mkdir -p build
if [[ ! -f "$archive" ]]; then
    curl -fsSL --retry 2 "https://codeload.github.com/RetroPie/tyrquake/tar.gz/$pin" -o "$archive.part"
    mv "$archive.part" "$archive"
fi
[[ $(shasum -a 256 "$archive" | cut -d' ' -f1) == "$expected" ]]
patch_id=$(shasum -a 256 upstream.patch | cut -d' ' -f1)
source_dir="$project/build/tyrquake-$pin"
if [[ ! -f "$source_dir/.mojo-patch" || $(cat "$source_dir/.mojo-patch") != "$patch_id" ]]; then
    stage=$(mktemp -d "$project/build/.source.XXXXXXXX")
    trap 'rm -rf "$stage"' EXIT
    tar -xzf "$archive" -C "$stage" --strip-components=1
    (cd "$stage" && patch -s -p1 < "$project/upstream.patch")
    mkdir -p "$source_dir"
    rsync -rc --delete "$stage/" "$source_dir/"
    printf '%s\n' "$patch_id" > "$source_dir/.mojo-patch"
    rm -rf "$stage"
    trap - EXIT
fi
out="$project/build/$target"
mkdir -p "$out"
sdl_inc=${SDL2_INCLUDE:-"$(sdl2-config --prefix)/include/SDL2"}
compiler=(build --emit object)
common=(USE_SDL=Y USE_X86_ASM=N CD_TARGET=null APP_BUNDLE=N STRIP=true
        "MQ_INCLUDE=$project/src" "MQ_OBJECTS=$out/qc.o $out/engine.o $out/snapshot.o $out/resources.o"
        "BUILD_DIR=$out/obj" "BIN_DIR=$out")
if [[ $target == unoq ]]; then
    compiler+=(--target-triple aarch64-unknown-linux-gnu --target-cpu cortex-a53)
    sdk="$project/build/sdk"
    [[ -r "$sdk/lib/libSDL2.so" && -r "$sdk/lib/libGL.so" && -r "$sdk/include/GL/gl.h" ]] || {
        echo "Prepare the ARM64 link SDK with ./prepare-sdk.sh." >&2;exit 1; }
    common+=(TARGET_OS=UNIX TARGET_UNIX=linux "CC=$zig cc -target aarch64-linux-gnu.2.34 -mcpu=cortex_a53"
             "CFLAGS=-O2 -std=gnu11 -fno-strict-aliasing"
             "SDL_CFLAGS=-I$sdl_inc -I$sdk/include" "SDL_LFLAGS=-L$sdk/lib -lSDL2")
else
    common+=("SDL_CFLAGS=-I$sdl_inc" "SDL_LFLAGS=$(sdl2-config --libs)")
fi
for module in qc engine snapshot resources; do
    "$mojo" "${compiler[@]}" "src/$module.mojo" -o "$out/$module.o"
done
make -C "$source_dir" -j"${JOBS:-6}" "${common[@]}" "$out/tyr-quake" "$out/tyr-glquake"
