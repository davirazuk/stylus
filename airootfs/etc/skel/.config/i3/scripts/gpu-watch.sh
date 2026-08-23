#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Say something when the graphics are broken.
#
#  A graphics driver that stops working does not announce itself. X falls back
#  to drawing on the processor, every window still appears, and the machine is
#  simply slow - until something asks for a game, and Steam exits with a
#  message about libGL that names nothing a student can act on.
#
#  Nobody is going to run `stylus-gpu --check` on a machine that looks like it is
#  working. So the machine checks itself, once, shortly after login, and says
#  so where it cannot be missed. Clicking the notification opens the repair.
#
#  Quiet when there is nothing wrong, which is almost always.
# ─────────────────────────────────────────────────────────────────────────────
set -u

# Long enough for polybar, dunst and the compositor to be up: a notification
# sent before dunst exists goes nowhere at all.
sleep 25

command -v stylus-gpu >/dev/null 2>&1 || exit 0
command -v notify-send >/dev/null 2>&1 || exit 0

# The live session cannot be repaired in any way that survives a reboot, and
# the installer already asks about drivers. Nagging there is noise.
[[ -d /run/archiso ]] && exit 0

# --why is --check with the answer on one line. The generic version of this
# notification said "a placa de vídeo não está funcionando direito" for every
# machine and every fault alike, which tells somebody that something is wrong
# and nothing about what - so the second time it appears it reads as noise. The
# sentence naming the actual fault was already being computed and thrown away.
WHY=$(stylus-gpu --why 2>/dev/null) && exit 0

TITLE="A placa de vídeo não está funcionando direito"
BODY="Os jogos e o Steam podem não abrir. Clique aqui para o STYLUS verificar e consertar sozinho."
[[ -n $WHY ]] && BODY="$WHY

Clique aqui para o STYLUS verificar e consertar sozinho."

# libnotify 0.8 can carry a clickable action and blocks until it is chosen or
# the notification is dismissed. Where that is not available the notification
# still says what to do, so the message never depends on it.
if notify-send --help 2>&1 | grep -q -- '--action'; then
    chosen=$(notify-send --app-name=STYLUS --urgency=critical \
                --hint=string:x-dunst-stack-tag:stylus-gpu \
                --icon=video-display \
                --action=fix="Verificar e consertar" \
                --expire-time=0 \
                "$TITLE" "$BODY")
    [[ $chosen == fix ]] && exec stylus-term "Vídeo e jogos" stylus-gpu --fix
else
    notify-send --app-name=STYLUS --urgency=critical \
        --hint=string:x-dunst-stack-tag:stylus-gpu \
        --icon=video-display \
        --expire-time=0 \
        "$TITLE" \
        "${WHY:-Os jogos e o Steam podem não abrir.}

Abra o menu do STYLUS e escolha «Vídeo e jogos»."
fi
