#!/bin/sh
set -e
cd "$(dirname "$0")"

export VITASDK="$HOME/vitasdk"
export PATH="$VITASDK/bin:$PATH"

mkdir -p build
cd build
cmake .. "$@"
make -j"$(nproc)"
echo "═══ construido ═══"
ls -la *.vpk 2>/dev/null || ls -la *.self
