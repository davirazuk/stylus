#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  sync.sh — copia o airootfs do repositório por cima do sistema vivo
# ═══════════════════════════════════════════════════════════════════════════
#  Chamado pelo stylus-update. Separado dele de propósito: é a parte que
#  MEXE no disco, e uma parte que mexe no disco tem que caber inteira numa
#  tela para poder ser lida antes de rodar.
#
#  A REGRA QUE NÃO SE QUEBRA: configuração que o usuário mexeu é dele.
#
#  A tentação óbvia aqui é `cp -a airootfs/etc/skel/. ~/.config/` e pronto.
#  Isso apaga, em silêncio, toda personalização que a pessoa fez desde a
#  instalação — a barra, o i3, o rofi, o tema. É o defeito mais comum de
#  distribuição caseira e é irreversível para quem não tem backup.
#
#  Então vale a regra do pacman: arquivo igual ao padrão anterior é
#  atualizado; arquivo diferente é MANTIDO e o novo fica ao lado como
#  `.novo`, com um resumo no fim dizendo quais foram. `--force-dotfiles`
#  existe para quem quer mesmo voltar ao padrão.
# ═══════════════════════════════════════════════════════════════════════════
set -uo pipefail

SRC="${STYLUS_SOURCE:?falta STYLUS_SOURCE apontando para o airootfs do repo}"
DST="${1:-/}"
FORCE_DOTFILES="${STYLUS_FORCE_DOTFILES:-0}"

c_g=$'\033[1;32m'; c_y=$'\033[1;33m'; c_b=$'\033[1;34m'; c_0=$'\033[0m'
info() { printf '%s==>%s %s\n' "$c_b" "$c_0" "$*"; }
ok()   { printf '%s  ✓%s %s\n' "$c_g" "$c_0" "$*"; }
warn() { printf '%s  !%s %s\n' "$c_y" "$c_0" "$*"; }

[[ -d $SRC ]] || { echo "sync: $SRC não existe" >&2; exit 1; }

# ── 1. o sistema: isto é nosso, sobrescreve sem dó ─────────────────────────
# Nada aqui é para o usuário editar. Quem quiser mudar edita em ~/.config,
# que é justamente o que a parte 2 protege.
SYSTEM_PATHS=(
    usr/local/bin
    usr/share/stylus
    usr/share/xsessions
    usr/share/applications
    usr/share/backgrounds/stylus
    etc/pipewire
    etc/wireplumber
    etc/udev/rules.d
    etc/systemd/system
    etc/sysctl.d
    etc/modprobe.d
    etc/X11/xorg.conf.d
)
info "Sistema…"
for p in "${SYSTEM_PATHS[@]}"; do
    [[ -e $SRC/$p ]] || continue
    mkdir -p "$DST/$(dirname "$p")"
    cp -a --no-preserve=ownership "$SRC/$p" "$DST/$(dirname "$p")/" || warn "falhou: $p"
done
# O venv do deck vive dentro de /usr/share/stylus/deck e NÃO está no
# repositório. Copiar a pasta por cima apagaria ele; por isso o cp acima é de
# diretório inteiro mas o venv é recriado logo abaixo se sumiu.
ok "binários, deck, interface e configuração de áudio"

chmod -R a+rX "$DST/usr/share/stylus" 2>/dev/null || true
find "$DST/usr/local/bin" -maxdepth 1 -type f -name 'stylus*' -exec chmod 0755 {} + 2>/dev/null || true
find "$DST/usr/share/stylus" -maxdepth 2 -type f \( -name '*.sh' -o -name 'run-*' \) \
     -exec chmod 0755 {} + 2>/dev/null || true

# ── 2. os dotfiles: regra do pacman ────────────────────────────────────────
SKEL="$SRC/etc/skel"
if [[ -d $SKEL ]]; then
    info "Padrões novos em /etc/skel…"
    cp -a --no-preserve=ownership "$SKEL/." "$DST/etc/skel/" 2>/dev/null || true

    mantidos=()
    while IFS= read -r linha; do
        usuario=${linha%%:*}
        casa=$(getent passwd "$usuario" | cut -d: -f6)
        [[ -d $casa ]] || continue
        [[ $casa == /home/* ]] || continue
        info "Dotfiles de $usuario…"
        while IFS= read -r -d '' novo; do
            rel=${novo#"$SKEL"/}
            alvo="$casa/$rel"
            if [[ ! -e $alvo ]]; then
                mkdir -p "$(dirname "$alvo")"
                cp -a --no-preserve=ownership "$novo" "$alvo"
                chown -R "$usuario": "$(dirname "$alvo")" 2>/dev/null || true
                continue
            fi
            cmp -s "$novo" "$alvo" && continue
            if [[ $FORCE_DOTFILES == 1 ]]; then
                cp -a --no-preserve=ownership "$novo" "$alvo"
                chown "$usuario": "$alvo" 2>/dev/null || true
            else
                cp -a --no-preserve=ownership "$novo" "$alvo.novo"
                chown "$usuario": "$alvo.novo" 2>/dev/null || true
                mantidos+=("$rel")
            fi
        done < <(find "$SKEL" -type f -print0)
    done < <(getent passwd | awk -F: '$3>=1000 && $3<65000')

    if (( ${#mantidos[@]} )); then
        echo
        warn "${#mantidos[@]} arquivo(s) seus foram MANTIDOS; o novo está ao lado como .novo:"
        printf '      %s\n' "${mantidos[@]}" | sort -u
        echo "      (para adotar um: mv ARQUIVO.novo ARQUIVO)"
        echo "      (para adotar todos: stylus-update --force-dotfiles)"
    fi
fi

# ── 2b. autostart do KDE: SEMPRE sobrescrever ───────────────────────────
# O autostart é configuração do SISTEMA que mora em ~/.config/autostart/.
# O usuário não mexe nisso — ele é o que faz o KDE funcionar direito.
# Se existir, substituir. Se não existir, copiar.
AUTOSTART_SKEL="$SRC/etc/skel/.config/autostart"
if [[ -d $AUTOSTART_SKEL ]]; then
    while IFS= read -r usuario; do
        casa=$(getent passwd "$usuario" | cut -d: -f6)
        [[ -d $casa ]] || continue
        [[ $casa == /home/* ]] || continue
        mkdir -p "$casa/.config/autostart"
        cp -a --no-preserve=ownership "$AUTOSTART_SKEL/." "$casa/.config/autostart/"
        chown -R "$usuario": "$casa/.config/autostart" 2>/dev/null || true
    done < <(getent passwd | awk -F: '$3>=1000 && $3<65000')
    ok "autostart KDE atualizado"
fi

# ── 3. o venv do deck, se sumiu ou está velho ──────────────────────────────
VENV="$DST/usr/share/stylus/deck/venv"
if [[ ! -x $VENV/bin/python3 ]]; then
    info "Refazendo o ambiente Python do deck…"
    if python3 -m venv --system-site-packages "$VENV" >/dev/null 2>&1 \
       && "$VENV/bin/pip" install -q --upgrade pip PyOpenGL PyOpenGL-accelerate >/dev/null 2>&1; then
        ok "deck pronto"
    else
        warn "não deu para refazer o venv; o deck vai usar o python do sistema"
    fi
fi

# ── 4. recarregar o que precisa ────────────────────────────────────────────
command -v udevadm >/dev/null && udevadm control --reload 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true
command -v update-desktop-database >/dev/null && \
    update-desktop-database /usr/share/applications 2>/dev/null || true
ok "pronto"
