#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
#  Start picom with a backend and a feature set the machine can actually use.
#
#  picom's glx backend needs a working GPU render node. Without one - a VM with
#  plain VGA, or a machine with no graphics driver - picom still starts, still
#  redirects every window offscreen, and then fails to paint them. The result is
#  a desktop where the wallpaper and the bar are visible and *every window is
#  invisible*: terminals, the launcher, everything. It looks exactly like the
#  applications are crashing when they are running perfectly well.
#
#  So: hardware GL when the render node is there, xrender otherwise. xrender is
#  software, slower, and works everywhere.
#
#  Animations need a second test. A render node says the machine can composite,
#  not that it can afford to redraw a window forty times while it opens. The
#  netbooks and 2010-era laptops this runs on have a render node and a GPU that
#  shares system memory with a two-core CPU; there, per-frame work during every
#  window open is felt directly. Below the thresholds the desktop is still
#  composited - rounded corners, shadows, fading all stay - it simply does not
#  animate.
#
#  Both tests only ever take work away. Nothing here makes a machine do more
#  than it did before, which is the point: the failure mode of guessing wrong
#  is a plainer desktop, never a slower one.
#
#  STYLUS_PICOM_ANIMATIONS=1 forces them on, =0 forces them off.
# ─────────────────────────────────────────────────────────────────────────────

CFG="${XDG_CONFIG_HOME:-$HOME/.config}/picom"

# MemTotal is in kB; 3.5 GiB in kB, so that a "4 GB" machine reporting 3.8
# still counts as one.
MIN_RAM_KB=3670016
MIN_CORES=4

want_animations() {
    case "${STYLUS_PICOM_ANIMATIONS:-}" in
        1) return 0 ;;
        0) return 1 ;;
    esac
    [ -f "$CFG/picom-animated.conf" ] || return 1

    ram=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null)
    cores=$(nproc 2>/dev/null)
    # Unknown is treated as capable: this must not silently downgrade a machine
    # just because something could not be read.
    [ -n "$ram" ] && [ "$ram" -lt "$MIN_RAM_KB" ] && return 1
    [ -n "$cores" ] && [ "$cores" -lt "$MIN_CORES" ] && return 1
    return 0
}

if [ -e /dev/dri/renderD128 ]; then
    if want_animations; then
        exec picom -b --config "$CFG/picom-animated.conf"
    fi
    exec picom -b
else
    exec picom -b --backend xrender
fi
