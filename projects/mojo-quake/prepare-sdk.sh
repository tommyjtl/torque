#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
dest=$(pwd)/build/sdk
board=${QUAKE_BOARD:-arduino@tommy-uno-q.local}
headers=${GL_INCLUDE:-$(brew --prefix mesa)/include}
[[ -f "$headers/GL/gl.h" && -f "$headers/KHR/khrplatform.h" ]]
mkdir -p "$dest"/{include,lib}
for name in GL KHR; do
    [[ -e "$dest/include/$name" ]] || ln -s "$headers/$name" "$dest/include/$name"
done
for pair in 'SDL2 libSDL2-2.0.so.0' 'GL libGL.so.1'; do
    read -r name soname <<< "$pair"
    ssh -4 -o BatchMode=yes -o ConnectTimeout=5 "$board" "cat /usr/lib/aarch64-linux-gnu/$soname" > "$dest/lib/lib$name.so.part"
    file "$dest/lib/lib$name.so.part" | grep -q 'ARM aarch64'
    mv "$dest/lib/lib$name.so.part" "$dest/lib/lib$name.so"
done
