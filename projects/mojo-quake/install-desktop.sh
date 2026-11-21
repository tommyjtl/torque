#!/usr/bin/env bash
# Run on the UNO Q as the desktop user from an extracted release package.
set -euo pipefail
cd "$(dirname "$0")"
root=${XDG_DATA_HOME:-"$HOME/.local/share"}/mojo-quake
applications=${XDG_DATA_HOME:-"$HOME/.local/share"}/applications
desktop=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")
pak="$root/media/id1/pak0.pak"
[[ $(uname -m) == aarch64 && -f "$pak" ]]
printf '%s  %s\n' 35a9c55e5e5a284a159ad2a62e0e8def23d829561fe2f54eb402dbc0a9a946af "$pak" | sha256sum -c --status
sha256sum -c --status SHA256SUMS
release_id=$(sha256sum SHA256SUMS | cut -c1-20)
mkdir -p "$root/releases" "$applications" "$desktop" "$root/profile/id1"
stage=$(mktemp -d "$root/releases/.install.XXXXXXXX")
trap 'rm -rf "$stage"' EXIT
install -m 755 tyr-quake tyr-glquake mojo-quake "$stage/"
install -m 644 SHA256SUMS quake.png quake.desktop.in source.tar.gz COPYING "$stage/"
target="$root/releases/$release_id"
if [[ -d "$target" ]]; then
    (cd "$target" && sha256sum -c --status SHA256SUMS)
    rm -rf "$stage"
else
    mv -T "$stage" "$target"
fi
# Keep each launch and save coherent when a new release is installed.
stage=$(mktemp -d "$root/releases/.desktop.XXXXXXXX")
ln -s "releases/$release_id" "$stage/current"
sed "s|@ROOT@|$root|g" "$target/quake.desktop.in" > "$stage/mojo-quake.desktop"
if command -v desktop-file-validate >/dev/null; then desktop-file-validate "$stage/mojo-quake.desktop"; fi
mv -Tf "$stage/current" "$root/current"
install -m 644 "$stage/mojo-quake.desktop" "$applications/mojo-quake.desktop"
install -m 755 "$stage/mojo-quake.desktop" "$desktop/Mojo-Quake.desktop"
if command -v gio >/dev/null; then gio set -t string "$desktop/Mojo-Quake.desktop" metadata::trusted true 2>/dev/null || true; fi
printf 'Installed %s at %s\n' "$release_id" "$desktop/Mojo-Quake.desktop"
