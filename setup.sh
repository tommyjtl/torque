#!/usr/bin/env bash
# Run from a reviewed checkout on the UNO Q. Credentials are read privately.
set +x
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$root/install/stage.py" "$@"
