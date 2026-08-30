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
    usr/share/color-schemes
    usr/share/Kvantum
    usr/share/qt5ct
    usr/share/qt6ct
    # AS TRÊS TELAS QUE VÊM ANTES DA ÁREA DE TRABALHO. Elas estavam só no
    # branding-sync.sh — que roda na INSTALAÇÃO — e não aqui, que é o caminho
    # normal de receber um conserto. Quem instalou há dois meses e roda
    # `stylus-update` recebia a paleta nova em tudo menos no GRUB, no plymouth
    # e no login: as três primeiras coisas que a máquina desenha. É a mesma
    # lição da lista escrita à mão do branding-sync, do outro lado.
    usr/share/grub/themes/stylus
    usr/share/plymouth/themes/stylus
    usr/share/sddm/themes/stylus
    usr/share/icons/hicolor
    etc/os-release              # é o que faz a máquina se chamar STYLUS
    etc/systemd/journald.conf.d/stylus-limits.conf
    etc/systemd/zram-generator.conf
    etc/pipewire
    etc/wireplumber
    etc/udev/rules.d
    etc/sysctl.d
    etc/modprobe.d
    etc/X11/xorg.conf.d
)
# O que NÃO entra na lista, e por quê:
#
#   etc/sddm.conf.d/stylus.conf   tem `[Autologin] User=stylus`, e o
#       instalador APAGA essas duas linhas ao instalar de propósito (não há
#       autologin sem senha numa máquina de verdade). Copiá-lo de volta a cada
#       atualização ressuscitaria o autologin — para um usuário que na
#       máquina instalada nem existe.
#   etc/skel                      é a parte 2, com a regra do pacman.
#   etc/systemd/system            veja o bloco abaixo.
# ── as unidades do systemd, uma a uma ──────────────────────────────────────
#  `etc/systemd/system` ESTAVA na lista acima, copiado inteiro. Só que essa
#  pasta, dentro do airootfs, não é "as unidades do STYLUS": é o estado do
#  systemd do MEDIUM AO VIVO inteiro. Dentro dela vão junto:
#
#      multi-user.target.wants/   com choose-mirror, pacman-init, livecd-talk,
#                                 sshd, vboxservice, vmtoolsd, hv_*…
#      sound.target.wants/        o livecd-alsa-unmuter, que desmuta a placa
#                                 por cima da configuração de quem usa
#      getty@tty1.service.d/      autologin de ROOT no tty1
#      etc-pacman.d-gnupg.mount   um tmpfs por cima do chaveiro do pacman
#
#  Num `stylus-update` rodado numa máquina instalada — que é o caminho normal
#  de receber um conserto — tudo isso desembarcava lá e passava a ligar no
#  boot. O branding-sync.sh já tinha aprendido essa lição e usa lista de
#  permissão desde sempre, com o motivo escrito no cabeçalho; aqui a lição
#  não tinha chegado.
#
#  Nada disto precisava vir por aqui de qualquer forma: as unidades do archiso
#  entram na ISO direto do airootfs, pelo mkarchiso. O sync.sh serve para
#  atualizar um sistema que já existe, e ali o que é nosso são estas:
info "Unidades do systemd…"
mkdir -p "$DST/etc/systemd/system"
for u in "$SRC"/etc/systemd/system/stylus-*.service; do
    [[ -e $u ]] || continue
    cp -a --no-preserve=ownership "$u" "$DST/etc/systemd/system/" || warn "falhou: $(basename "$u")"
done
# O nosso ajuste no paccache: guardar uma versão de cada pacote em vez de três.
if [[ -f $SRC/etc/systemd/system/paccache.service.d/stylus-keep-one.conf ]]; then
    mkdir -p "$DST/etc/systemd/system/paccache.service.d"
    cp -a --no-preserve=ownership \
       "$SRC/etc/systemd/system/paccache.service.d/stylus-keep-one.conf" \
       "$DST/etc/systemd/system/paccache.service.d/" || warn "falhou: stylus-keep-one.conf"
fi
ok "$(find "$DST/etc/systemd/system" -maxdepth 1 -name 'stylus-*.service' 2>/dev/null | wc -l) unidades"

info "Sistema…"
for p in "${SYSTEM_PATHS[@]}"; do
    [[ -e $SRC/$p ]] || continue
    mkdir -p "$DST/$(dirname "$p")"
    cp -a --no-preserve=ownership "$SRC/$p" "$DST/$(dirname "$p")/" || warn "falhou: $p"
done
# Mesma razão do build.sh: o __pycache__ que nasce quando alguém roda um teste
# no clone não é do sistema, e vinha junto no cp -a acima.
find "$DST/usr/share/stylus" "$DST/usr/local/bin" \
     -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

ok "binários, biblioteca, interface e configuração de áudio"

chmod -R a+rX "$DST/usr/share/stylus" 2>/dev/null || true
find "$DST/usr/local/bin" -maxdepth 1 -type f -name 'stylus*' -exec chmod 0755 {} + 2>/dev/null || true
find "$DST/usr/share/stylus" -maxdepth 2 -type f \( -name '*.sh' -o -name 'run-*' \) \
     -exec chmod 0755 {} + 2>/dev/null || true

# As duas seções abaixo mexem na casa de gente de verdade, e descobrem quem
# são pelo `getent passwd` — que responde sobre ESTE sistema, não sobre $DST.
# Com um destino que não é a raiz viva (uma cópia de teste, um /mnt), elas
# escreviam na casa do usuário da máquina que está rodando o comando. Nada
# aqui vale esse risco: fora da raiz viva, os dotfiles ficam de fora.
casas_de_verdade() {
    [[ $(readlink -f "$DST") == / ]] || return 1
    getent passwd | awk -F: '$3>=1000 && $3<65000'
}

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
                # O arquivo e as pastas ATÉ ele, uma a uma — não um
                # `chown -R` na pasta de cima.
                #
                # **Sintoma:** o /etc/skel tem seis arquivos na RAIZ da casa
                # (.bashrc, .xinitrc, .dialogrc…). Para qualquer um deles que
                # ainda não existisse, o `dirname` é a casa inteira, e o
                # `chown -R` saía andando por ela: a coleção de música com
                # cem mil arquivos, os caches, o .git de quem clonou o
                # repositório — e o celular montado por WebDAV, atravessado
                # arquivo por arquivo pela rede. Minutos de espera no meio de
                # um `stylus-update`, sem uma linha na tela dizendo o que
                # estava acontecendo.
                chown "$usuario": "$alvo" 2>/dev/null || true
                d=$(dirname "$alvo")
                while [[ $d == "$casa"/* ]]; do
                    chown "$usuario": "$d" 2>/dev/null || true
                    d=$(dirname "$d")
                done
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
    done < <(casas_de_verdade)

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
    tocadas=0
    while IFS= read -r usuario; do
        casa=$(getent passwd "$usuario" | cut -d: -f6)
        [[ -d $casa ]] || continue
        [[ $casa == /home/* ]] || continue
        mkdir -p "$casa/.config/autostart"
        cp -a --no-preserve=ownership "$AUTOSTART_SKEL/." "$casa/.config/autostart/"
        chown -R "$usuario": "$casa/.config/autostart" 2>/dev/null || true
        tocadas=$(( tocadas + 1 ))
    done < <(casas_de_verdade | cut -d: -f1)
    # Só avisa se mexeu mesmo. Fora da raiz viva o casas_de_verdade não devolve
    # ninguém e o laço acima não roda — mas esta linha dizia "atualizado" do
    # mesmo jeito, prometendo um trabalho que não aconteceu.
    (( tocadas )) && ok "autostart atualizado em $tocadas casa(s)"
fi

# ── 3. o venv do deck, que não existe mais ─────────────────────────────────
#  Havia aqui um venv de sistema em /usr/share/stylus/lib/venv, refeito toda
#  vez que sumia. Ele existia por UM pacote — o PyOpenGL, que não está nos
#  repositórios do Arch — e o único que o usava era o deck. Sem o deck, ele é
#  só uma pasta de centenas de megabytes que ninguém abre; então quando ela
#  ainda estiver lá de uma instalação antiga, tiramos.
VELHO_VENV="$DST/usr/share/stylus/lib/venv"
if [[ -d $VELHO_VENV ]]; then
    rm -rf "$VELHO_VENV" && ok "o venv do deck (que não existe mais) foi removido"
fi

# ── 4. recarregar o que precisa ────────────────────────────────────────────
command -v udevadm >/dev/null && udevadm control --reload 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true
command -v update-desktop-database >/dev/null && \
    update-desktop-database /usr/share/applications 2>/dev/null || true
ok "pronto"
