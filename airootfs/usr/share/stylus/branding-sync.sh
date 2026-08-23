#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  branding-sync.sh — põe o STYLUS dentro de um sistema recém-instalado
# ═══════════════════════════════════════════════════════════════════════════
#  O pacstrap instala PACOTES. Tudo que faz este sistema ser o STYLUS — os
#  comandos, o deck, a tela cheia, o tema, a configuração de áudio, o
#  /etc/skel — não vem de pacote nenhum: vem do airootfs, e o airootfs só
#  existe dentro do medium ao vivo. Alguém tem que copiar.
#
#  Esse alguém é este arquivo, e ele NÃO EXISTIA. O stylus-install chamava
#  `/usr/share/stylus/branding-sync.sh` e só avisava quando não achava, então
#  a instalação terminava dizendo "concluída" e entregava um Arch com i3 e
#  nenhum comando `stylus` na máquina. É o defeito mais silencioso possível:
#  tudo funciona, e nada é o STYLUS.
#
#      branding-sync.sh /mnt          copia para o sistema montado em /mnt
#
#  A LISTA É UMA LISTA DE PERMISSÃO, de propósito. Copiar `/etc` inteiro do
#  medium levaria junto o autologin, o sudoers sem senha, o usuário `stylus`,
#  os hooks do archiso no mkinitcpio e a tampa do notebook configurada para
#  não suspender nunca — cada um deles um defeito que só aparece semanas
#  depois. O que vai é o que está escrito aqui embaixo, e mais nada.
# ═══════════════════════════════════════════════════════════════════════════
set -uo pipefail

DST=${1:-}
SRC=${STYLUS_SOURCE:-/}

c_g=$'\033[1;32m'; c_y=$'\033[1;33m'; c_b=$'\033[1;34m'; c_0=$'\033[0m'
info() { printf '%s==>%s %s\n' "$c_b" "$c_0" "$*"; }
ok()   { printf '%s  ✓%s %s\n' "$c_g" "$c_0" "$*"; }
warn() { printf '%s  !%s %s\n' "$c_y" "$c_0" "$*"; }

[[ -n $DST ]]   || { echo "uso: branding-sync.sh <raiz-de-destino>" >&2; exit 2; }
[[ -d $DST ]]   || { echo "branding-sync: $DST não existe" >&2; exit 1; }
# Copiar por cima da raiz viva é o que o `stylus update` faz, com a regra do
# pacman para proteger o que a pessoa mexeu. Aqui não há essa proteção porque
# o destino acabou de nascer — então o destino não pode ser este sistema.
[[ $(readlink -f "$DST") == / ]] && {
    echo "branding-sync: o destino é a raiz viva. Para atualizar este sistema use \`stylus update\`." >&2
    exit 1; }
[[ -d $DST/usr && -d $DST/etc ]] || {
    echo "branding-sync: $DST não parece um sistema instalado (sem /usr ou /etc)" >&2; exit 1; }

falhou=0
copiar() {  # copiar <caminho relativo à raiz>   (arquivo ou pasta)
    local rel=$1 origem="$SRC/$1" destino="$DST/$1"
    [[ -e $origem ]] || return 0
    mkdir -p "$(dirname "$destino")" || { warn "não deu para criar $(dirname "$rel")"; falhou=1; return 1; }
    # --no-preserve=ownership: o dono dentro do medium é o do medium. Os donos
    # que importam no destino são acertados no fim.
    if cp -a --no-preserve=ownership "$origem" "$(dirname "$destino")/"; then
        return 0
    fi
    warn "não deu para copiar $rel"; falhou=1; return 1
}

# ── 1. os comandos ─────────────────────────────────────────────────────────
info "Comandos…"
mkdir -p "$DST/usr/local/bin"
for f in "$SRC"/usr/local/bin/stylus*; do
    [[ -e $f ]] || continue
    copiar "usr/local/bin/$(basename "$f")"
done
# yay: o `stylus app` cai nele para o que não vem em pacote oficial.
copiar usr/local/bin/install-yay
# choose-mirror e livecd-sound ficam de fora: são do medium ao vivo, e o
# livecd-sound desmuta placas de som em cima de qualquer configuração que a
# pessoa tenha feito depois.
ok "$(find "$DST/usr/local/bin" -maxdepth 1 -name 'stylus*' 2>/dev/null | wc -l) comandos"

# ── 2. o STYLUS propriamente dito ──────────────────────────────────────────
info "Deck, tela cheia e ferramentas…"
copiar usr/share/stylus
# Todas as unidades de usuário, por glob e não por lista. Escrito à mão, isto
# trazia só a do celular — e a do lado do disco, acrescentada depois, ficava
# para trás sem ninguém notar: o aviso de virar o lado simplesmente nunca
# chegava numa máquina instalada, e nada explicava.
for u in "$SRC"/usr/lib/systemd/user/stylus-*.service; do
    [[ -e $u ]] || continue
    copiar "usr/lib/systemd/user/$(basename "$u")"
done
for s in stylus stylus-desktop stylus-music; do
    copiar "usr/share/xsessions/$s.desktop"
done
# Os lançadores do menu (Mod+D). O sync.sh já copia usr/share/applications
# numa máquina que existe; numa que acabou de nascer, aqui.
for f in "$SRC"/usr/share/applications/stylus-*.desktop; do
    [[ -e $f ]] || continue
    copiar "usr/share/applications/$(basename "$f")"
done
ok "/usr/share/stylus"

# ── 3. a identidade visual ─────────────────────────────────────────────────
info "Identidade visual…"
copiar usr/share/backgrounds/stylus
copiar usr/share/grub/themes/stylus
copiar usr/share/plymouth/themes/stylus
copiar usr/share/sddm/themes/stylus
for px in 16 22 24 32 48 64 128 256 512; do
    copiar "usr/share/icons/hicolor/${px}x${px}/apps/stylus.png"
done
# /etc/os-release é o que faz a máquina se chamar STYLUS em tudo que pergunta:
# o fastfetch, o menu do GRUB, o relatório de erro. No Arch ele é um link para
# /usr/lib/os-release; substituir por arquivo de verdade funciona porque o
# systemd lê /etc primeiro, e é o que o archiso faz na própria imagem.
copiar etc/os-release
ok "papel de parede, GRUB, plymouth, SDDM, ícones"

# ── 4. configuração de sistema que é NOSSA ─────────────────────────────────
#  Só o que o STYLUS escreveu. Nada de /etc inteiro — veja o cabeçalho.
info "Configuração…"
copiar etc/pipewire          # a tese do sistema: não reamostrar
copiar etc/wireplumber       # o ALSA precisa dos DOIS para trocar de taxa
copiar etc/sddm.conf.d/stylus.conf
copiar etc/systemd/system/stylus-fontcache.service
copiar etc/systemd/system/stylus-gpu-fallback.service
copiar etc/systemd/system/paccache.service.d/stylus-keep-one.conf
copiar etc/systemd/journald.conf.d/stylus-limits.conf
copiar etc/systemd/zram-generator.conf
copiar etc/stylus            # onde procurar a coleção, por padrão
# O que fica de fora, e por quê:
#   sddm.service.d/stylus-keep-tty1.conf  mantém o console de resgate do
#       archiso no tty1; numa instalação não há console de resgate para manter.
#   logind.conf.d/do-not-suspend.conf     fecha a tampa e não suspende. Certo
#       num pendrive de demonstração, errado num notebook: a bateria acaba
#       dentro da mochila.
#   sysusers.d/stylus.conf, tmpfiles.d/stylus-home.conf   criam o usuário do
#       medium ao vivo. A instalação tem o usuário da pessoa.
#   mkinitcpio.conf.d/archiso.conf, mkinitcpio.d/linux.preset   os hooks que
#       montam um squashfs de dentro de um pendrive.
#   sudoers.d/10-stylus-live              sudo sem senha.
ok "áudio, sessão gráfica, journal, zram"

# ── 5. os padrões de dotfile ───────────────────────────────────────────────
#  Tem que ser antes do useradd: o useradd copia o /etc/skel que existir NA
#  HORA. Depois dele, a casa da pessoa nasceria vazia e só a próxima conta
#  criada teria a área de trabalho do STYLUS.
info "/etc/skel…"
copiar etc/skel
ok "i3, polybar, rofi, fish, picom, dunst, gtk, qt"

# ── 6. o ambiente Python do deck ───────────────────────────────────────────
#  O venv é construído dentro do chroot na hora de fazer a ISO, porque o
#  PyOpenGL não existe nos repositórios do Arch. Copiá-lo é o que faz o deck
#  abrir na primeira vez sem rede — mas um venv é amarrado à VERSÃO do python
#  que o criou, e o sistema instalado acabou de pegar o python de hoje. Se as
#  versões não baterem, o venv existe e não roda, que é pior do que não
#  existir: o stylus-ui prefere o venv quando ele está lá.
VENV="$DST/usr/share/stylus/deck/venv"
if [[ -d $VENV ]]; then
    py_alvo=$(basename "$(find "$DST/usr/lib" -maxdepth 1 -name 'python3.*' -type d 2>/dev/null | sort -V | tail -1)" 2>/dev/null)
    py_venv=$(basename "$(find "$VENV/lib" -maxdepth 1 -name 'python3.*' -type d 2>/dev/null | sort -V | tail -1)" 2>/dev/null)
    if [[ -n $py_alvo && -n $py_venv && $py_alvo != "$py_venv" ]]; then
        warn "o venv do deck é do $py_venv e o sistema tem $py_alvo — refazendo depois"
        rm -rf "$VENV"
    fi
fi

# ── 7. modos ───────────────────────────────────────────────────────────────
#  O airootfs viaja como zip em algumas mãos, e zip não guarda bit de
#  execução. O profiledef.sh reaplica isso na ISO; aqui é a mesma garantia
#  para a cópia.
find "$DST/usr/local/bin" -maxdepth 1 -type f -name 'stylus*' -exec chmod 0755 {} + 2>/dev/null
chmod 0755 "$DST/usr/local/bin/install-yay" 2>/dev/null
chmod -R a+rX "$DST/usr/share/stylus" 2>/dev/null
find "$DST/usr/share/stylus" -maxdepth 2 -type f -name '*.sh' -exec chmod 0755 {} + 2>/dev/null
find "$DST/usr/share/stylus/tools" "$DST/usr/share/stylus/deck" -maxdepth 1 -type f -name '*.py' \
     -exec chmod 0755 {} + 2>/dev/null
find "$DST/etc/skel" -type f \( -name '*.sh' -o -name '.xinitrc' \) -exec chmod 0755 {} + 2>/dev/null
chown -R 0:0 "$DST/usr/local/bin" "$DST/usr/share/stylus" "$DST/etc/skel" 2>/dev/null

if (( falhou )); then
    warn "alguma coisa não foi copiada; veja as linhas acima"
    exit 1
fi
ok "STYLUS instalado em $DST"
