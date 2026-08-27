#!/usr/bin/env bash
# polybar webdav — mostra quando o celular está montado
MONTAGEM="$HOME/.local/share/stylus/celular"
if mountpoint -q "$MONTAGEM" 2>/dev/null; then
    n=$(find "$MONTAGEM" -maxdepth 2 -type d 2>/dev/null | wc -l)
    echo "%{F#7ed99e}󰄹%{F-} $((n>0?n-1:0))"
else
    echo ""
fi
