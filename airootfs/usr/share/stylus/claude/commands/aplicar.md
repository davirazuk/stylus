---
description: aplica o clone em ~/stylus nesta máquina, sem passar pelo GitHub
---

Aplique o que está em `~/stylus` nesta máquina, na ordem, parando no primeiro
erro e me dizendo onde parou:

1. `git -C ~/stylus status --short` — se houver coisa não commitada, mostre o
   que é antes de continuar. Aplicar sujeira sem avisar é como se perde a
   noção do que a máquina está rodando.
2. `~/stylus/tools/check.sh --fast` — se falhar, **pare aqui** e conserte
   antes. É a diferença entre um conserto e um segundo defeito.
3. `sudo STYLUS_SOURCE=~/stylus/airootfs /usr/share/stylus/sync.sh`

Depois diga, em uma linha cada, o que precisa ser reiniciado para a mudança
aparecer — e só o que precisa mesmo, olhando o que o sync tocou:

- ferramenta de terminal (`/usr/local/bin/stylus*`): nada, já vale;
- serviço de usuário (`stylus-*.service`): `systemctl --user restart NOME`;
- barra, i3, rofi (`~/.config`): `$mod+Shift+r` reinicia o i3 no lugar;
- PipeWire ou WirePlumber (`/etc/pipewire`, `/etc/wireplumber`):
  `systemctl --user restart wireplumber pipewire pipewire-pulse` — **e diga
  antes que isso corta o som por um segundo**, porque se tem disco tocando
  ele vai ouvir.

Se o `sync.sh` deixar arquivos `.novo` em `~/.config`, liste-os e diga o que
mudou em cada um. Não os aplique por conta própria: aquele arquivo é dele.
