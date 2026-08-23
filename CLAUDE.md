# Instruções para o Claude — leia antes de qualquer coisa

Este arquivo existe para duas coisas: para você não gastar sessão
redescobrindo o que já foi descoberto, e para você não estragar o computador
de ninguém.

---

## 1. A regra que não se quebra

**Este repositório é o CÓDIGO-FONTE de uma distribuição, não a máquina.**

Editar arquivo dentro do repositório é o trabalho. Escrever fora dele não é.

Nunca rode, nem "só para testar":

| Nunca | Por quê |
| --- | --- |
| `stylus-update` | atualiza a máquina de verdade |
| `stylus-install` | formata disco |
| `tools/flash.sh` | apaga um pendrive (ou o disco errado) |
| `pacman -S/-R/-Syu` | mexe nos pacotes da máquina |
| `systemctl enable/start` | mexe nos serviços da máquina |
| `stylus-gpu --fix` | troca driver, escreve em `/etc` |
| qualquer escrita em `/etc`, `/usr`, `/boot` | idem |

Se ele pedir "conserta meu PC": você conserta o **código**, ele roda
`stylus-update`.

**Exceção**: se ele pedir explicitamente para construir a ISO ou gravar um
pendrive, isso é o trabalho — mas confirme o dispositivo antes de gravar.
`tools/flash.sh` recusa disco interno de propósito; não contorne isso.

---

## 2. Como se testa aqui

```
tools/check.sh          # as verificações. Rode ANTES de empurrar.
tools/check.sh --fast   # pula a conferência de pacotes (que usa rede)
```

Ele pega: sintaxe de shell, shellcheck, sintaxe de python, sintaxe de fish,
config do i3, link simbólico apontando para arquivo renomeado, nome de pacote
que não existe, ferramenta que o menu promete e não está lá, binário sem bit
de execução.

Construir a ISO leva ~30 min. `check.sh` leva segundos e pega quase tudo.

O deck tem o próprio teste, sem GL nem janela:
```
airootfs/usr/share/stylus/deck/tools/test_ritual.py
```

---

## 3. O mapa

```
profiledef.sh              identidade da ISO, modos de arquivo
packages.x86_64            os pacotes da ISO, agrupados e justificados
pacman.conf                pacman DA CONSTRUÇÃO (cache do hospedeiro)
build.sh                   mkarchiso nativo, com podman de reserva
tools/check.sh             as verificações
tools/flash.sh             grava no pendrive, com trava contra disco interno

airootfs/
  etc/pacman.conf          pacman do MEDIUM AO VIVO — multilib LIGADO (senão o
                              pacstrap do instalador morre em lib32-*)
  etc/pipewire/            ← a tese do sistema: não reamostrar
  etc/wireplumber/            (o ALSA precisa dos DOIS para trocar de taxa)
  etc/skel/                a área de trabalho (i3, polybar, rofi, fish)
  usr/local/bin/stylus*    todos os comandos
  usr/share/stylus/
    deck/                  o disco na tela (scope.py + vinyl.py)
    ui/                    a tela cheia (theme, model, app)
    tools/                 as ferramentas de coleção, em python
      _raiz.py             onde fica a coleção — UMA resposta para todas elas
    packages.install       o que uma máquina INSTALADA recebe (o instalador lê)
    packages.live-only     o que fica só na ISO, com o motivo escrito
    branding-sync.sh       copia o STYLUS para o sistema recém-instalado
    sync.sh                copia o airootfs por cima do sistema vivo
```

As três listas de pacote andam juntas por regra, não por disciplina: todo
pacote de `packages.x86_64` tem que estar em `packages.install` OU em
`packages.live-only` com o motivo. O `check.sh` recusa se alguma sobrar de
fora — foi assim que o instalador chegou a instalar outra distribuição
(LibreOffice, sem nada de música) por baixo da ISO do STYLUS.

---

## 4. Coisas que já custaram tempo

- **`/sdcard` é um LINK.** `find /sdcard ...` no Android devolve **zero
  linhas, sem erro**. Precisa de `find -L`. Isto fez a detecção da música do
  celular parecer que o aparelho estava vazio.
- **O `find` do Android sai com 1** sempre que esbarra numa pasta sem
  permissão, e sempre esbarra — mas devolve todo o resto. Tratar saída ≠ 0
  como falha joga fora milhares de linhas boas.
- **As duas metades da coleção não têm a mesma organização.** Aqui é
  `Artista/Álbum/faixa`, no celular costuma ser tudo solto numa pasta. Casar
  por caminho relativo não encontra nada; tem que cair para o nome do
  arquivo depois.
- **`api.alsa.multirate` é obrigatório** além de `allowed-rates`. Só a
  segunda faz o grafo "permitir" 44,1k e nunca usar.
- **PyOpenGL não existe nos repositórios do Arch.** O deck usa um venv
  construído dentro do chroot pelo `customize_airootfs.sh`.
- **O deck TAMBÉM precisa de `python-pyaudio`** (PortAudio), e esse existe no
  repositório — o `scope.py` faz `import pyaudio` no topo e abre o monitor de
  áudio. Sem ele o deck não abre, e como a interface o lança com o stderr no
  `/dev/null`, o sintoma é a tela não mudar e nada explicar. Está nas duas
  listas de pacote; o import agora é guardado e dá recado em vez de traceback.
- **O `/etc/pacman.conf` do medium ao vivo NÃO vem do perfil** — vem do pacote
  pacman, com o multilib comentado. O instalador põe `lib32-gamemode` em toda
  máquina, então o `pacstrap` morria em "target not found", depois de formatar
  o disco. Por isso existe `airootfs/etc/pacman.conf` com multilib ligado, e o
  instalador confere os nomes ANTES de tocar no disco.
- **`stylus-mode` derruba a sessão para trocar de modo** e conta com o SDDM
  reentrar sozinho. No medium ao vivo isso exige `Relogin=true` no
  `sddm.conf.d/stylus.conf`; sem isso a troca cai no login pedindo senha, em
  vez de "meio segundo de preto e você está do outro lado".
- **Nunca copie `/etc/skel` por cima de `~/.config`.** Apaga tudo que a
  pessoa personalizou, em silêncio. `sync.sh` segue a regra do pacman:
  diferente é mantido, o novo vira `.novo`.
- **`pkill -f <padrão>` casa com o próprio shell da ferramenta Bash** e mata
  a sessão. Use `pgrep` + confira `/proc/<pid>/cmdline`, ou `pkill -x`.
- **Uma FUNÇÃO do fish chamada `stylus` fica na frente do `/usr/local/bin/stylus`.**
  Existia uma, herdada, e ela respondia "comando desconhecido" para `deck`,
  `library`, `phone`, `record` — a CLI inteira do README, morta no shell
  padrão do sistema. Não crie função com o nome de um comando nosso.
- **O que a área de trabalho promete tem que existir.** A config do i3 abria
  `stylus-welcome`, `stylus-software` e `install-stylus` — nenhum dos três
  jamais existiu — e o `xfce4-terminal`, que não está em pacote nenhum. O
  `check.sh` agora confere posição de comando (`exec`, `bindsym … exec`,
  `alias`) e os caminhos que a sessão aponta.
- **Nunca escreva `/home/<alguém>/` à mão.** Nove ferramentas de `tools/`
  traziam `/home/davirazuk/Músicas` dentro (uma delas com o nome da coleção
  de uma pessoa como raiz). Em qualquer outro computador — no medium ao vivo
  o usuário é `stylus` — o `stylus covers`, `gaps`, `tags`, `check` e
  `suggest` varriam uma pasta inexistente e diziam que estava tudo bem. A
  raiz vem do `tools/_raiz.py`, que pergunta ao `vinyl.library_root()`. O
  `check.sh` recusa qualquer casa que não seja a do usuário do medium.
- **A ISO liga no MODO MÚSICA.** Então é lá que o instalador precisa estar:
  a interface mostra a seção INSTALAR quando existe `/run/archiso`, e só
  nesse caso. Antes não havia caminho nenhum do pendrive até o instalador.

---

## 5. O tom

Comentário explica **por que**, não o que. O código já diz o que faz; o que
se perde é o motivo — e o motivo quase sempre é um defeito que já aconteceu.
Quando consertar algo não óbvio, escreva o sintoma no comentário: é isso que
impede o conserto de ser desfeito por engano seis meses depois.

Texto que o usuário vê é em português. Comentário de código acompanha o
arquivo em que está.
