# The clock, on the right-hand side.
#
# The Big Picture session has no bar at all, and a fullscreen application on the
# desktop covers polybar, so a terminal is often the only thing on screen. This
# puts the time where it costs nothing: fish draws the right prompt only when
# the line has room for it, and drops it as soon as what you are typing gets
# long enough to need the space.

function fish_right_prompt --description 'STYLUS right prompt'
    set -l dim (set_color 7fa392)
    set -l reset (set_color normal)

    echo -n -s $dim (date '+%H:%M') $reset
end
