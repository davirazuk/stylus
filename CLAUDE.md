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

**Exceção 2 — você está NUMA máquina STYLUS.** Se `/etc/os-release` disser
`ID=stylus`, esta sessão não é um contêiner: é o computador de alguém, com o
áudio tocando. Aí existe `~/.claude/CLAUDE.md` (instalado pelo `stylus
claude`) e ele manda no que é sobre a máquina — aplicar pelo `sync.sh` e pelo
`stylus-update` passa a ser justamente o serviço. Este arquivo continua
mandando em tudo que é sobre o código. O resto da tabela acima continua de pé
em qualquer caso: `stylus-install` formata disco nos dois lugares.

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

O deck e a tela cheia têm testes próprios, sem GL e sem janela — os dois
rodam com o vídeo "dummy" do SDL, então não precisam de X:
```
airootfs/usr/share/stylus/deck/tools/test_ritual.py   # a cerimônia, o disco
airootfs/usr/share/stylus/ui/tools/test_ui.py         # todas as seções
```
O `check.sh` já chama o da interface. O do deck quer um álbum de verdade:
`test_ritual.py --album PASTA`.

E há uma construção de verdade, na nuvem, para quando `check.sh` não basta:
`.github/workflows/build-iso.yml`. Ela roda o `check.sh` dentro de um Arch
com pacman e já pegou três nomes de pacote que o Arch mudou por baixo
(`fdk-aac`→`libfdk-aac`, `nvidia-dkms`→`nvidia-open-dkms`) — coisa que
nenhuma máquina sem pacman tem como notar.

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
    claude/                as instruções do Claude Code NA máquina, e os
                             comandos /aplicar e /diagnostico
    ui/tools/test_ui.py    a tela cheia exercitada sem X (o check.sh roda)
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
- **A estante varre TODAS as pastas configuradas, não só a primeira.** Era só
  a primeira que existisse, e isso tornava impossível ter a coleção em dois
  lugares: o `stylus webdav` montava o celular, escrevia a pasta na
  configuração, e ela era ignorada — que é pior do que não funcionar, porque
  a pessoa fez o que era para fazer e não aconteceu nada. Quem varre é
  `vinyl.library_roots()`, que desduplica por caminho real (senão um link
  para a mesma pasta mostra cada disco duas vezes). Os palpites (`~/Music`,
  `/srv/music`…) só valem quando NADA foi configurado.
- **Escrever a pasta do celular na estante não pode apagar a de casa.** A
  partir do momento em que existe uma linha configurada, os palpites deixam
  de valer — então escrever só o celular fazia a coleção local sumir. O
  `stylus webdav` escreve a de casa primeiro quando o arquivo ainda não
  existe.
- **`grep -v` sai com 1 quando não sobra nada.** Um `grep -v X arq > tmp && mv`
  não move nada quando X era a única linha — foi assim que desmontar o celular
  deixava a estante apontando para uma pasta vazia.
- **Empurrar ETIQUETA não passa pelo proxy de git da sessão do Claude** (ramo
  passa). A Release sai por marcador `[release]` na mensagem do commit, e o
  `gh release create` cria a etiqueta do lado do servidor.
- **A lista do `branding-sync.sh` é escrita à mão, e por isso esquece.** Ela
  trazia `stylus-phone-watch.service` por nome; a unidade do lado do disco,
  acrescentada depois, ficava para trás — numa máquina instalada o aviso de
  virar o lado simplesmente nunca chegava, e nada explicava. Agora vai por
  glob, e o `check.sh` RODA o branding-sync para uma pasta temporária e
  confere o que caiu lá. É a única conferência que executa a coisa de
  verdade, e é a que pega o que leitura não pega.
- **`find A -name X -o -path Y` só desce em A.** A conferência acima nasceu
  com essa forma e a metade das unidades nunca era conferida — ela passava
  verde exatamente sobre o defeito que existia para pegar. Duas buscas.
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

## 6. Mudanças Recentes e Pendências

- **Bit-perfect audio:** PipeWire was resampling everything to 48kHz because the audio device was being held open. Reduced `session.suspend-timeout-seconds` to 1 second in `airootfs/etc/wireplumber/wireplumber.conf.d/51-stylus-alsa.conf` to encourage bit-perfect playback.
- **`stylus-deck` sync:** Repository version of `stylus-deck` was outdated and missing fixes, causing playback issues. Synced it with the working local installation.

### Futuras Melhorias
- **Launcher rework:** The now playing part in the launcher needs to be reworked to remove empty space.
- **Ritual vinyl:** The vinyl effect needs to be reworked, as it was built on top of the oscilloscope code and looks bad.
- **Missing commands:** Investigate and add any commands missing from the repository that are present in the local installation.
