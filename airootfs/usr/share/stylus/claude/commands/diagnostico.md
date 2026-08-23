---
description: junta o estado real desta máquina antes de chutar qualquer coisa
---

Antes de teorizar, olhe. Colete o que interessa ao problema que eu descrevi
— não tudo, só o ramo certo — e depois me diga o que **os dados** dizem,
separando o que você viu do que você está supondo.

**som**
`stylus audio`; `wpctl status`; `pactl info`;
`cat /proc/asound/card*/pcm*p/sub*/hw_params` (a taxa de verdade, não a
prometida); `systemctl --user status pipewire wireplumber pipewire-pulse`

**o deck, a tela cheia, os serviços**
`systemctl --user status 'stylus-*'`;
`journalctl --user -b -n 200 --no-pager | grep -i stylus`;
`ls -la ~/.local/share/stylus/`

**a sessão gráfica**
`echo $XDG_SESSION_TYPE`; `cat ~/.config/stylus/mode`;
`journalctl -b -u sddm --no-pager | tail -50`;
`tail -50 ~/.local/share/xorg/Xorg.0.log`

**a coleção**
`stylus library`; `stylus check`; `cat ~/.config/stylus/library` (se existir)

**a máquina**
`cat /etc/os-release`; `git -C /var/lib/stylus/repo log -1 --oneline`;
`uname -r`; `pacman -Q | wc -l`; `df -h /`; `free -h`

Regras:

- Comando que **lê** pode rodar direto. Nada aqui escreve; se você achar que
  precisa escrever para diagnosticar, pergunte primeiro.
- `pkill -f` mata a sua própria sessão. Use `pgrep` e confira
  `/proc/<pid>/cmdline`.
- Se o conserto for no código, ele é em `~/stylus` e depois `/aplicar`.
  Nunca editando `/etc` ou `/usr` à mão — some no próximo `stylus-update`.
