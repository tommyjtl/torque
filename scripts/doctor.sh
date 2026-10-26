#!/usr/bin/env bash
set +x
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$root/scripts/doctor.py" "$@"
