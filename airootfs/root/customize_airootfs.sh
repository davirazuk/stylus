#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  Roda DENTRO do chroot, durante a construção da ISO.
# ═══════════════════════════════════════════════════════════════════════════
#  Só entra aqui o que não dá para resolver copiando arquivo: coisas que
#  precisam dos pacotes já instalados, ou de rede, ou de gerar algo derivado.
# ═══════════════════════════════════════════════════════════════════════════
set -e -u

locale-gen

# ── serviços ───────────────────────────────────────────────────────────────
systemctl enable NetworkManager.service bluetooth.service sddm.service \
                 systemd-timesyncd.service power-profiles-daemon.service \
                 2>/dev/null || true
systemctl set-default graphical.target 2>/dev/null || true

# rtkit é o que permite ao PipeWire pegar a prioridade de tempo real que ele
# pede. Sem isso cada falha de buffer vira um clique no meio de uma parte
# silenciosa, que é onde ela mais aparece.
systemctl enable rtkit-daemon.service 2>/dev/null || true

# ── o usuário do live medium ───────────────────────────────────────────────
# O grupo e as participações vêm do sysusers; aqui só o que sobra.
chown -R 1000:1000 /home/stylus 2>/dev/null || true
usermod -s /usr/bin/fish stylus 2>/dev/null || true

# A estante do live medium aponta para a pasta padrão. Quem estiver testando
# a ISO com um HD cheio de música muda com `stylus library <pasta>`.
install -d -m 0755 /etc/stylus
# O til aqui é DADO, não caminho: quem lê este arquivo é o
# _read_library_conf do vinyl.py, que passa cada linha por expanduser. Expandir
# no shell escreveria /root/Music, que é a casa errada.
# shellcheck disable=SC2088
printf '%s\n' '# uma pasta por linha; a primeira que existir é a estante' \
              '~/Music' '/run/media' '/mnt' > /etc/stylus/library

# O modo padrão é MÚSICA. É o que este sistema é.
install -d -o 1000 -g 1000 -m 0755 /home/stylus/.config/stylus
echo music > /home/stylus/.config/stylus/mode
chown 1000:1000 /home/stylus/.config/stylus/mode

# ── cache de fontes, para o primeiro desenho não engasgar ─────────────────
fc-cache -f >/dev/null 2>&1 || true
update-desktop-database /usr/share/applications 2>/dev/null || true
