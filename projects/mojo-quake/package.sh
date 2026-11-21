#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
project=$(pwd)
out="$project/build/mojo-quake-unoq.tar.gz"
stage=$(mktemp -d "$project/build/.package.XXXXXXXX")
trap 'rm -rf "$stage"' EXIT
export COPYFILE_DISABLE=1
cp build/unoq/{tyr-quake,tyr-glquake} mojo-quake install-desktop.sh quake.desktop.in COPYING "$stage/"
tar -xzOf build/tyrquake.tar.gz 'tyrquake-c0553b4ca60b608b68c133faab4f2462f7c5c195/icons/tyrquake-1024x1024.png' > "$stage/quake.png"
tar --format=ustar --exclude=__pycache__ -czf "$stage/source.tar.gz" COPYING README.md build.sh prepare-sdk.sh package.sh install-desktop.sh \
    mojo-quake quake.desktop.in prepare_shareware.py inspect_pak.py verify_snapshot.py verify_timing.py verify_campaign.py verify_music.py verify_resources.py agent_view src upstream.patch replays evidence fixture build/tyrquake.tar.gz
(cd "$stage" && shasum -a 256 tyr-quake tyr-glquake mojo-quake quake.png quake.desktop.in source.tar.gz COPYING > SHA256SUMS)
tar --format=ustar --exclude=__pycache__ -czf "$stage/bundle.tmp" -C "$stage" tyr-quake tyr-glquake mojo-quake quake.png quake.desktop.in \
    source.tar.gz COPYING install-desktop.sh SHA256SUMS
mv "$stage/bundle.tmp" "$out"
echo "$out"
