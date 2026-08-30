# Você está dentro de um STYLUS

Este arquivo é a memória do Claude Code **nesta máquina**. Ele é instalado
pelo `stylus claude` em `~/.claude/CLAUDE.md` e vale em qualquer pasta.

Se você está lendo isto, você não está num contêiner limpo olhando um
repositório: você está **na máquina de música de alguém**, com o áudio
tocando, o disco montado e a coleção inteira do lado. Isso muda duas coisas
— o que você consegue descobrir, e o que você consegue quebrar.

---

## 1. As duas metades

```
  ~/stylus                  a FONTE. um clone de git, seu para editar.
  /etc  /usr  /var          a MÁQUINA. gerada a partir da fonte.
```

A máquina não é escrita à mão. Ela é o `airootfs/` da fonte copiado por
cima, pelo `sync.sh`, que o `stylus-update` chama.

**Daí a regra que não se quebra aqui:**

> Consertar é editar em `~/stylus`. Depois aplicar. Nunca o contrário.

Editar `/usr/local/bin/stylus-deck` direto funciona — até o próximo
`stylus-update`, que copia a fonte por cima e apaga o conserto **sem dizer
nada**. Duas semanas depois o defeito volta e ninguém liga uma coisa à
outra. É a pior forma de perder trabalho: a que não deixa rastro.

Vale para `/etc/pipewire`, `/usr/share/stylus`, `/usr/local/bin` e
`/usr/share/xsessions` — tudo isso o `sync.sh` sobrescreve sem dó, de
propósito, porque nada ali é para o usuário editar.

`~/.config` é a exceção: ali é do usuário, e o `sync.sh` **mantém** o que
foi mexido, deixando o padrão novo ao lado como `.novo`. Se você mudar um
dotfile em `~/.config` direto, ele sobrevive — mas o resto das máquinas não
recebe. Se a mudança é boa para todo mundo, ela vai em
`airootfs/etc/skel/`.

---

## 2. O ciclo

```
 1.  edite em ~/stylus
 2.  ~/stylus/tools/check.sh          as conferências. segundos, pega quase tudo.
 3.  sudo STYLUS_SOURCE=~/stylus/airootfs /usr/share/stylus/sync.sh
                                      aplica ESTE clone na máquina, sem passar
                                      pelo GitHub. é assim que se testa.
 4.  funcionou? commit, push.
 5.  sudo stylus-update --stylus      confere que o caminho de verdade também
                                      traz o conserto (ele clona do GitHub).
```

O passo 3 é o que esta máquina te dá e nenhuma sessão remota tem: você
aplica e **vê acontecer**. Use isso. Um conserto de áudio conferido só por
leitura é um palpite.

Depois do passo 3, o que já estava rodando continua com o código velho.
Coisa de shell e de ferramenta de terminal pega na hora; serviço quer
`systemctl --user restart stylus-...`; a sessão gráfica inteira quer
`$mod+Shift+r` (i3 reinicia no lugar, sem perder as janelas).

---

## 3. O que é seguro fazer aqui

Ler a máquina é o motivo de você estar nela. Nada disto machuca:

| Pergunta | Como se olha |
| --- | --- |
| o caminho do som está bit-perfect? | `stylus audio` |
| o grafo do PipeWire, de verdade | `pw-dump`, `pw-cli info all`, `wpctl status` |
| que taxa a placa está mesmo usando | `cat /proc/asound/card*/pcm*p/sub*/hw_params` |
| um serviço morreu? | `systemctl --user status stylus-*`, `journalctl --user -u ... -b` |
| por que a sessão não subiu | `journalctl -b -u sddm`, `~/.local/share/xorg/Xorg.0.log` |
| o que está instalado | `pacman -Q`, `pacman -Qi PACOTE` |
| a estante enxerga o quê | `stylus check`, `stylus library` |
| esta versão é qual | `git -c safe.directory=/var/lib/stylus/repo -C /var/lib/stylus/repo log -1 --oneline` |

A interface escreve em `~/.local/share/stylus/`. Quando a tela
"não muda e nada explica", o motivo quase sempre está ali ou no
`journalctl --user`.

---

## 4. O que não se faz, nem para testar

| Nunca | Por quê |
| --- | --- |
| `stylus-install` | formata disco. esta máquina já está instalada. |
| `tools/flash.sh` | grava por cima de um pendrive — ou do disco errado |
| `pacman -Rns` em lote | esta máquina é a máquina dele, não um contêiner |
| editar `/etc` e `/usr` à mão | some no próximo update (§1) |
| `pkill -f <padrão>` | casa com o shell da própria ferramenta e mata a sessão. use `pgrep` e confira `/proc/<pid>/cmdline`, ou `pkill -x`. |
| `rm -rf` em `~/Músicas` | é a coleção. ela não tem backup em lugar nenhum. |

`sudo pacman -Syu` e `stylus-update` **são permitidos aqui** — é uma
máquina de verdade e atualizar é o serviço. Mas avise antes: uma
atualização de kernel no meio de um disco tocando não é o que ele pediu.

---

## 5. Quando o repositório também estiver aberto

`~/stylus/CLAUDE.md` é o guia da fonte e continua valendo inteiro: o mapa
das pastas, as três listas de pacote que andam juntas, o `check.sh`, a
lista de coisas que já custaram tempo. **Leia-o.** Ele é mais específico
que este arquivo em tudo que é código.

Uma coisa só muda de lá para cá: lá, "não rode `stylus-update` nem para
testar" é regra, porque lá não existe máquina para atualizar — a sessão
roda num contêiner descartável e o comando só faria estrago. Aqui existe
máquina, e aplicar pelo `sync.sh` ou pelo `stylus-update` é justamente o
que se veio fazer. O resto da lista de "nunca" continua de pé.

---

## 6. O tom

Comentário explica **por quê**, não o quê. Quando consertar algo não óbvio,
escreva o **sintoma** no comentário — é isso que impede o conserto de ser
desfeito por engano seis meses depois.

Texto que o usuário vê é em português. Comentário de código acompanha o
arquivo em que está.
