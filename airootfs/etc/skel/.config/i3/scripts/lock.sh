#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  The implementation moved to /usr/local/bin/stylus-lock, so that the desktop,
#  the Big Picture session and the launcher all lock the same way. This wrapper
#  stays because existing i3 configurations and xss-lock point at this path.
# ─────────────────────────────────────────────────────────────────────────────
set -u

command -v stylus-lock >/dev/null && exec stylus-lock "$@"

# Fallback for a machine that has not taken the update yet.
exec i3lock -c 10241d -e -f
