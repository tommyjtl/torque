#!/bin/bash
set -eu
cd "$(dirname "$0")"
exec python3 serve.py --system next --launch --port 18801
