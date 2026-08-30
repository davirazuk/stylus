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
- **O `sync.sh` preserva o `~/.config` — de propósito, e isso tem preço.**
  Nada que você acrescentar ao `etc/skel/.config/i3/config` chega em quem já
  instalou: aquele arquivo é do usuário agora, e o novo padrão fica ao lado
  como `.novo`. Foi assim que o `stylus-side-watch` nunca subiu nesta
  máquina. O que precisa alcançar máquina existente vai em `/usr/local/bin`
  ou em `~/.config/autostart`, que o sync sobrescreve.
- **O i3 não lê `~/.config/autostart`; o KDE lê.** É por isso que o
  `stylus-fundo` existe e é seguro rodar duas vezes: o i3 chama pelas linhas
  `exec` dele, o KDE pelo autostart, e o `stylus-session` chama para os dois.
- **`git` recusa ler repositório de outro dono.** O `/var/lib/stylus/repo` é
  do root, e um `git -C` ali, rodando como usuário, falha com "detected
  dubious ownership" — pelo **stderr**, com stdout vazio. Quem só olha o
  stdout acha que não tem versão e cai calado num plano B. Precisa de
  `git -c safe.directory=/var/lib/stylus/repo`.
- **Procurar processo por pedaço de linha de comando encontra você mesmo.**
  Não é só o `pkill -f`: o `pgrep -f "stylus-side-watch"` casa com o shell
  que está rodando o próprio comando, porque o padrão está na linha dele.
  Um teste inteiro passou verde assim, sem nunca ter subido o processo.
  Compare argumento por argumento, pelo basename, lendo `/proc/*/cmdline`.
- **`done < arquivo 2>/dev/null` deixa o erro escapar.** As redireções valem
  na ordem em que aparecem, e "arquivo inexistente" acontece antes de o
  `2>/dev/null` existir. Ao varrer `/proc`, onde processos morrem no meio da
  varredura, isso vira ruído no journal a cada login. `2>/dev/null` primeiro.
- **Sombra preta não desenha nada sobre o INK.** O fundo é (7,8,11): não há
  para onde escurecer. Medido, a sombra que existia mudava no máximo 7
  unidades somando os três canais. Num fundo escuro, peso vem de LUZ — uma
  aresta iluminada, uma lombada. Ver `T.sleeve` no `ui/theme.py`.
- **`ceil(total / teto_do_lado)` dá disco de TRÊS lados.** Um LP de 45 min —
  a forma mais comum que um disco tem — saía com três lados de quinze. Duas
  coisas: 22 min é o lado CONFORTÁVEL e não o teto (o lado A de Abbey Road
  tem 23min30; o teto virou 26), e quem se arredonda para cima é o número de
  DISCOS, porque o disco é o objeto e ele tem dois lados sempre.
- **Duração zero não é "não sei", é "não dura nada".** Faixa que nem o
  mutagen nem o ffprobe leem entrava com 0, e três num disco de doze tiram um
  quarto do total: some um LADO inteiro, o "vira em X" mente e a agulha do
  deck aponta para o sulco errado, tudo sem erro nenhum. As que faltam
  recebem a MEDIANA das que deram (a média quebra num disco com uma faixa de
  vinte minutos), marcadas com `estimada`.
- **`dirname` de um ENDEREÇO é a mesma string para tudo.** Um disco da rede
  não tem caminho: o dirname de `https://x.invalid/123.flac` é
  `https:/x.invalid` para TODA playlist do Qobuz. Quem compara isso para
  saber "trocou de disco?" nunca troca. A pergunta certa é o `Album.folder`.
- **Lado sem `label` derruba a tela.** O lado único de uma playlist
  (`continuo`) saía sem rótulo — a etiqueta é posta num laço que o atalho da
  playlist pula — e a AGORA faz `side["label"]`. Toda playlist do Qobuz
  virava tela de erro. Dado que falta pode virar "LADO"; não pode virar
  traceback: use `.get` em desenho.
- **Camada de texto criada, desenhada e nunca alimentada.** As duas legendas
  do deck eram construídas no `main()` e desenhadas em todo quadro, e ninguém
  chamava `set_text` nelas: o deck nunca disse "vire o disco", que é a tese
  do sistema. As peças todas existiam (play_banner, banner(),
  caption_is_state(), a cor ALARM na paleta); faltava o último fio. Quando
  achar um helper que ninguém chama, desconfie de um recurso inteiro faltando
  — foi assim também com o `Nx` do diário e o "X min encostado no móvel".
- **Tecla que muda um campo e acende um ícone não é tecla.** O `[s]`
  (embaralhar) e o `[R]` (repetir) da AGORA viravam `not self.shuffle`, um
  toast e um ícone — e NENHUMA linha do programa contava ao mpv. A música
  seguia na mesma ordem enquanto a tela afirmava o contrário, que é pior do
  que não ter a tecla. Ler não pega: o método existe, tem o nome certo e faz
  alguma coisa. O teste põe um mpv de mentira e olha o que CHEGA nele.
- **Os endereços do Qobuz vencem em ~1 h; uma playlist de 200 faixas são 13.**
  Passada a hora, o mpv pede o endereço seguinte, leva 403, pula, leva 403 de
  novo, e varre o resto da lista em segundos — da poltrona é "a música parou
  sozinha", sem nada ligando aquilo a uma assinatura. Quem renova é o
  `stylus-side-watch` (já pergunta ao mpv de 2 em 2 s em que faixa está), com
  o `qid` que o manifesto guarda; a faixa que TOCA não é tocada, então não há
  corte no som. E `playlist-remove` tem que ir de TRÁS para a frente: do
  começo, cada remoção empurra o resto e metade da cauda velha sobrevive.
- **Com teto, "as primeiras N" são sempre as MESMAS.** Uma playlist de 853
  faixas com teto de 200 tinha 653 que o sistema nunca tocaria. O `--sortear`
  embaralha ANTES do corte — sortear depois embaralha as mesmas 200 de
  sempre, que é a armadilha desta feature e passa despercebida.
- **`set_alpha(None)` APAGA o SRCALPHA da superfície (pygame 2).** Não é
  "tirar o alfa de superfície e ficar com o por-pixel": é pôr o modo de
  mistura em NONE, e o blit vira cópia crua. O `T.halo` e o `T.disco`
  terminavam com ele em nome de um blit "3,6x mais rápido" — rápido porque
  não desenhava luz nenhuma, pintava por cima. Na tela: um quadrado PRETO de
  meia tela (o canto (0,0,0,0) do halo) com um disco de mostarda chapado
  dentro. O teste exigia o defeito (`get_alpha() is None`) e passava verde
  em cima dele. Meça o RESULTADO — blite num fundo colorido e veja se o
  canto continua colorido — nunca o atributo.
- **Os ícones do Nerd Font v3 estão no PLANO 15, não na área de uso privado
  do BMP.** O `fonte_para` tinha um atalho para `\ue000–\uf8ff` e não há um
  único ícone nosso ali: os 27 que o app.py usa são Material Design
  (F0000–FFFFD). Sem o atalho, numa máquina sem o Nerd Font o ícone escolhia
  a fonte do RÓTULO INTEIRO — e quem "cobre" uso privado é uma fonte de
  símbolos, sem letra latina. "Clone Hero" virava fileira de caixinhas.
- **Segmento de comprimento zero desenha NADA.** O `build_segs`/`build_strip`
  do ritual montam o quadrilátero a partir da normal do segmento: com
  comprimento zero a normal é zero e os quatro vértices caem no mesmo ponto.
  Duas coisas moravam no código sem nunca aparecer na tela por isso — as
  faíscas da agulha (um ponto duplicado "to make a tiny segment") e uma das
  poeiras (um ponto só num `build_strip`, que exige dois).
- **Conferência que roda como root não confere: ela EXECUTA.** A do `stylus
  app yay` no check.sh chamava o comando com um `sudo` de mentira — mas como
  root o `precisa_root` volta na hora e o `pacman -S git base-devel`
  acontece de verdade, o que é o caso do contêiner Arch da construção na
  nuvem. Ela ficava vermelha dizendo que o argumento se perdia. Baixe para o
  `nobody` (`setpriv`) antes de executar qualquer coisa que peça root.
- **Peça escrita numa lista e ausente da outra é invisível, não quebrada.**
  A polybar tinha `[module/webdav]` inteiro — script próprio, verde quando o
  celular está montado, com a contagem de pastas — e ele não estava em
  NENHUMA das três linhas `modules-*`. A barra nunca o desenhou; quem rodava
  `stylus webdav` não tinha na tela nenhuma confirmação de que deu certo. O
  `[module/xwindow]` idem. É a mesma família do `stylus-welcome` que o i3
  abria e nunca existiu, e do `set_text` que ninguém chamava no deck: ler um
  arquivo por vez não pega nada, porque o defeito só existe na RELAÇÃO entre
  as duas listas. Quando duas listas se referem uma à outra, confira as duas
  direções.
- **Ícone que não existe é um espaço, e um espaço não parece defeito.** Três
  módulos internos da barra (volume, mudo, data) tinham `format-prefix` com
  dois ESPAÇOS e uma cor de ícone. Os módulos de script trazem o ícone de
  dentro; os internos não têm de onde tirar. O pior era o do mudo: o aviso
  mais importante da barra existia como um vermelho sem forma.
- **O sistema tinha DOIS terminais com paletas diferentes.** O alacritty (i3)
  usa o `palette`; o Konsole que o `stylus-switch-kde` escreve usava um
  esquema de origem desconhecida — azul 0,102,204 onde a paleta diz
  91,206,250. A conferência da paleta não pegava porque varre o `/etc/skel` e
  compara HEXADECIMAL, e aquilo mora num heredoc do `/usr/local/bin` em
  R,G,B decimal. Dois formatos e dois lugares é onde a deriva se esconde. (E
  `Color8..15` não são chaves do Konsole — as claras se chamam
  `Color0Intense`; as oito que estavam lá nunca foram lidas.)
- **Número fixo de largura no desenho é sempre a tela de quem escreveu.** Em
  um dia: a grade dos JOGOS somava 940 px num corpo de 1645 (setecentos de
  nada à direita, e dois rótulos cortados dentro dos quadros estreitos); o
  painel de saída da AJUSTES tinha `min(340, …)` com 660 px vazios ao lado; o
  calendário do DIÁRIO parava trezentos pixels antes da lista que acompanha;
  o disco da tela cheia empurrava o nome da faixa para fora da tela. Nenhum
  estoura. Todos leem como página montada para outro monitor.
- **Cópia inteira de uma pasta de configuração, esquecida.** Havia DUAS
  árvores da polybar — `/etc/skel/.config/polybar` e `/etc/polybar` — com
  nove dos dez arquivos diferentes, e a de baixo com a paleta velha dentro.
  E ela nem podia funcionar: o polybar procura no `~/.config` antes do
  `/etc`, então a de baixo só valeria para quem NÃO tem `~/.config/polybar`
  — e todo `exec` dela aponta para `~/.config/polybar/scripts/…`, que nesse
  caso não existe. Caminho de reserva quebrado nos dois lados.
- **Lista de cores SEM NOME é onde os papéis se embaralham.** O
  `qt5ct/colors/stylus.conf` são vinte hexadecimais numa linha, na ordem do
  enum `QPalette::ColorRole`. Estavam trocados: `WindowText` tinha a MESMA
  cor de `Window` (todo rótulo de todo aplicativo Qt era preto sobre preto) e
  `Base` — o fundo de campo de texto e de lista — era o âmbar da seleção.
  Ler o arquivo não pega nada. A conferência tem que ser sobre o RESULTADO:
  texto e fundo do mesmo par têm que estar longe um do outro.
- **A paleta valia para a área de trabalho e não para o que vem ANTES dela.**
  O GRUB e o login do SDDM — a primeira e a segunda tela da máquina —
  estavam inteiros na paleta velha, mais um amarelo e um rosa do Catppuccin,
  porque a conferência de deriva varria o `/etc/skel` e o `/usr/share` do KDE
  e não aqueles dois. E o nome STYLUS, âmbar em todo o resto do sistema,
  aparecia em AZUL no login.
- **Varredura de teclado que desenha só no fim não vê quase nada.** A última
  tecla desfaz o estado que a anterior criou, e uma tecla que põe a tela num
  sub-estado quebrado não estoura ao ser apertada — estoura no quadro
  seguinte. E ela precisa rodar com o prato CHEIO também: com nada tocando,
  metade da AGORA nem é desenhada (o `draw` sai cedo pelo `_nothing`).
  Medido com um `raise` posto de propósito: a versão antiga passava verde.
- **Teste que ninguém roda é teste que não existe.** As 119 conferências do
  `test_ritual.py` ficaram de fora de tudo por precisarem de um `--album`
  que num contêiner não existe. O `check.sh` agora monta oito WAVs de
  silêncio com o módulo `wave` e roda.
- **"1 faixas".** A regra do plural estava escrita à mão em quinze lugares
  (`f"{n} faixas"`) e o caso do 1 faltava em todos: "1 discos", "posto há 1
  meses", "1 discos · 1 vezes". Não derruba nada e não some sozinho — só faz
  o sistema parecer traduzido por máquina, e o texto que a pessoa vê é a
  única parte dele que ela lê inteira. `model.plural`.
- **O sorteio lia a coleção inteira do disco.** O `draw_record` abria um
  `Album` de CADA candidato para aplicar um empurrãozinho de 15% pela hora do
  dia — quatro mil e quinhentos arquivos abertos (e um ffprobe por faixa que
  o mutagen não lê) para um ajuste que o próprio comentário chama de sutil.
  Sorteie pelo que é barato, tire uma dúzia de finalistas, e só neles pague o
  preço. Vale sempre que um peso caro decide pouco.
- **Conferência que reprova por falta de dependência ensina a ignorar a
  conferência.** O `check.sh` roda aqui, no contêiner Arch da nuvem e na
  máquina de quem mexe, e nem todos têm numpy, pygame e mutagen. Sem guarda,
  o vermelho dizia "o aviso do fim do lado manda a coisa errada" numa máquina
  onde ele está perfeito. Use o prefixo `PULA`, que vira um "—" amarelo.
- **Piso que não cabe não é piso, é vazamento com nome bonito.** A AGORA
  tinha dois: 260 px para o disco e 180 para a coluna de texto. Juntos, mais
  do que a largura de uma tela de 800 — e o bloco inteiro era desenhado para
  FORA dela. Quando dois pisos dividem uma largura, um deles tem que ceder, e
  quem cede é o DESENHO, não a informação.
- **Teste que mede a tela com o prato VAZIO não mede a metade que tem
  texto.** A conferência de colisão varria sete resoluções e passava verde
  sobre um vazamento da AGORA, porque com nada tocando o `draw` sai cedo pelo
  `_nothing`. Ela roda nos dois estados agora, e com nomes COMPRIDOS de
  propósito: é o comprimento que revela folga fixa, não o nome curto do fake.
- **Uma forma escolhida a dedo prova o caso escolhido a dedo.** O teste
  cobria "90 min → 4 lados" e passava verde enquanto um disco de 90 minutos
  em dezoito faixas de cinco saía com CINCO lados: o teste usa faixas de
  3min45, e a granularidade mais fina escondia o defeito. Varra a GRADE (de
  20 a 130 minutos × faixas de 2 a 9) e o defeito aparece na primeira volta.
  Vale para qualquer coisa com forma: resolução de tela, número de faixas,
  tamanho de coleção.
- **A mesma FRASE escrita em três telas deriva igual às cores.** "LADO A
  acabou — vire o disco" era escrito pela notificação, pelo deck e pelo aviso
  de tela cheia, e os três perguntavam "este é o último lado?". Num LP de
  dois lados isso acerta por acidente; num DUPLO, o fim do lado B pede para
  TROCAR de disco (você levanta e vai até a estante) e os três mandavam
  virar. A frase mora no `Album.gesto_do_lado`, junto dos lados. E note a
  condição que denuncia: `if ultimo and i == len(sides)-1` — a mesma coisa
  escrita duas vezes é o rastro de quem não sabia o que queria perguntar.
- **Teste com objeto de mentira passa por cima do caminho de verdade.** Ao
  mover uma decisão para o `vinyl.Album`, os dois testes que a cobriam
  continuaram com os seus fakes sem o método novo, caíram na reserva do
  `try/except` e ficaram VERDES. Monte um `Album` de verdade com
  `vinyl.Album.__new__(vinyl.Album)` — sem `__init__`, que iria ao disco.
- **`{{duration(...)}}` e `{{position(...)}}` do playerctl FORMATAM.** Eles
  devolvem "3:42" e "2:05", não números — e o código embaixo testava
  `isdigit()`, que dá falso, e caía num zero silencioso. Efeito: a duração
  era sempre 0, o limiar de scrobble caía nos 4 minutos fixos e **nenhuma
  música de menos de quatro minutos era scroblada, nunca**. Peça
  `{{mpris:length}}` cru (microssegundos) e `playerctl position` sem formato.
- **Relógio de parede não é tempo de escuta.** O scrobbler contava
  `time.time() - track_start`, então pausar não PARAVA o contador: almoço com
  a música pausada scroblava a faixa inteira. A conta é sobre a AGULHA —
  quanto a posição andou entre duas voltas do laço, e só quando o avanço é
  plausível (busca para frente e para trás não contam).
- **Unidade em `~/.config/systemd/user` com `[Install]` nunca sobe sozinha.**
  O `WantedBy` só vale depois de um `systemctl --user enable`, e nada chamava
  isso: o scrobbler e o botão do fone existiam e NUNCA rodaram. Pior, o lugar
  estava errado de qualquer jeito — o `sync.sh` preserva o `~/.config`, então
  unidade nova nunca alcança quem já instalou. Vigia novo vai no
  `stylus-fundo`, com uma guarda para não subir onde não tem o que fazer.
- **Quantas listas de extensão de áudio existem?** Eram SEIS, e discordavam:
  o vinyl tinha `.wma` e não `.shn`, o `stylus-audio` `.ape` e não `.shn`, e
  quatro ferramentas paravam em `.flac` e `.mp3`. Numa coleção em ALAC ou
  Opus o `stylus covers`, o `stylus suggest` e o gerador de playlist não
  achavam faixa nenhuma — e diziam que estava tudo bem. A resposta é uma só:
  `_raiz.audio_ext()`, que pergunta ao `vinyl.AUDIO_EXT`.
- **Folga fixa entre dois textos na mesma linha sempre quebra na máquina do
  outro.** O `- 300` reservado para o valor à direita não cabia o valor mais
  largo, e o nome do aparelho entrava por cima — só em quem tem placa de nome
  comprido. Meça com `T.largura`. O `test_ui.py` espiona todo `T.text` e
  reclama de retângulos que se cruzam.
- **"O outro lado resolve" e ninguém escreveu a resolução.** O agente do
  celular escreve a quarta coluna do scrobble — a PASTA — vazia de propósito,
  com um comentário dizendo "o PC resolve para a pasta dele". Essa resolução
  nunca existiu: as linhas iam para o `plays.tsv` com pasta vazia, que não é
  disco nenhum, e com o carimbo de AGORA em vez do do celular. E o comando
  terminava com "memória da coleção atualizada". É a família do `set_text`:
  a peça está lá, o fio não — e aqui o fio estava até DESCRITO no comentário
  do outro lado.
- **Agrupar por NOME o que sobra descarta o que sobra.** No plano de
  sincronia do celular, o que não casou com nada do outro lado era agrupado
  por nome de arquivo e só o melhor de cada grupo ia: de duas faixas
  chamadas "01 - Intro.flac", em álbuns diferentes, uma sumia sem aparecer em
  lista nenhuma. Agrupar por nome é a resposta certa para a pergunta "qual
  dos meus é AQUELE do outro lado?" e a errada para "o que falta lá?" — na
  segunda não há ambiguidade nenhuma para resolver.
- **Comparar nome de arquivo com maiúscula descarta meia coleção.** Um acervo
  passado por um Windows guarda `Folder.jpg` e `Cover.jpg`: o deck ficava sem
  capa NENHUMA e a estante caía no "primeira imagem em ordem alfabética", que
  ali é `AlbumArtSmall.jpg` ou `Back.jpg`. Eram cinco listas de nome de capa,
  e discordavam entre si — a mesma doença das seis listas de extensão. A
  resposta é uma só: `vinyl.find_cover` (e o `_raiz.find_cover` para as
  ferramentas).
- **Tela medida VAZIA não é tela medida.** As duas lojas eram exercitadas com
  `results` em [] — sem rede é o que acontece — então a grade, que é a tela
  inteira das duas, nunca tinha sido medida nem apertada por ninguém. Com
  disco dentro apareceram quatro colisões na primeira volta. É a mesma lição
  da AGORA com o prato vazio, e a mesma da estante de mentira com dois discos
  de nome curto: "Abbey Road" cabe em qualquer canto.
- **Ao medir o desenho, o RECORTE conta.** As grades desenham a fileira que
  está meio para fora e deixam o pygame cortar. Medindo o retângulo cru, a
  conferência acusou 182 textos "fora da tela" que na tela não aparecem — e
  uma conferência que grita sobre o que está certo é uma que se aprende a
  ignorar. Idem o painel de saída e o formulário, que são desenhados POR CIMA
  de propósito: feche-os antes de medir colisão.
- **`read` sem terminal volta na hora, vazio.** O `stylus webdav sozinho` roda
  como serviço: o `read` da senha voltava vazio e o `rclone config create`
  logo abaixo reescrevia o remoto SEM a senha guardada — apagando a que
  estava lá. Montava na primeira vez e nunca mais, com 401 inclusive à mão.
  Onde não há terminal, não pergunte: use o que já está guardado, ou pare com
  um recado.
- **Metade do sistema seguia o `XDG_CONFIG_HOME` e metade não.** Quem ESCREVE
  a configuração do STYLUS usa `~/.config` literal (o vinyl, o `stylus-mode`,
  o `stylus-wallpaper`, o `stylus-scrobble`); cinco leitores montavam o
  caminho com a variável. Numa máquina que a define, montar o celular não
  punha nada na estante, o scrobbler nunca subia e o papel de parede
  escolhido era trocado por cima. Dois lugares para a mesma coisa, e a metade
  que ninguém lê some em silêncio.
- **Campo escrito e nunca lido LÊ como recurso que existe.** O `Deck` tinha
  `side_index`, `pending_side` e `message` — que parecem o encanamento do
  aviso de virar o lado, a tese do projeto — e nenhum dos três era lido em
  lugar nenhum. Estado morto com nome de recurso é pior do que estado nenhum:
  da próxima vez alguém liga o fio no lugar errado.
- **A mesma tecla com dois significados nos dois modos.** O
  `stylus-kde-shortcuts` escrevia a regra ("quem aprende o atalho num modo não
  o perde no outro") e a quebrava em quatro das sete teclas: Meta+D abria o
  toca-discos no KDE e o menu de programas no i3. A mão aprende e erra, e
  ninguém desconfia da tecla — desconfia do programa.
- **Ferramenta de medir que não enxerga o tocador do sistema.** O `stylus
  audio` perguntava por MPRIS qual arquivo estava tocando, e o deck e o
  lançador tocam com mpv por SOCKET. Quem punha um disco e ia conferir o
  caminho do sinal recebia "nada tocando — ponha um disco e rode de novo".
  Quem pergunta o que está tocando pergunta ao socket primeiro; foi o mesmo
  defeito do módulo do disco na barra.
- **Tecla comida por quem vem antes dela.** O `App._key` trata o ESC (abrir o
  trilho) ANTES de passar a tecla para a tela, e a tela cheia do disco tinha
  um `if ev.key == K_ESCAPE and self.tela_cheia` que nunca rodava. Pior que
  não funcionar: o ESC ligava o trilho, que na tela cheia não é DESENHADO —
  o programa ficava num menu invisível comendo todas as teclas seguintes, e
  da poltrona isso é "o programa travou". Quando duas camadas tratam a mesma
  tecla, a de cima decide; e um estado que muda o desenho tem que estar
  visível em todo caminho que o liga.
- **Esticar não é cobrir.** O borrão de fundo da AGORA era escalado direto
  para o tamanho da tela: capa QUADRADA numa tela 16:9 saía com quase o dobro
  da largura. Escala pelo lado que precisa de mais e corta o resto — e a
  conta virou função (`_cobre`) para o teste poder varrer doze formas de capa
  e de tela sem desenhar nada.
- **Duas frentes para a mesma loja, e só uma aprendeu.** Os favoritos do
  Qobuz paginavam na estante do rofi e não na loja de tela cheia, que pedia
  60 numa chamada só; a busca pedia 100 lá e 25 aqui. Quem tem 87 favoritos
  via 60 numa tela e 87 na outra, sobre a mesma conta. Toda vez que existirem
  duas telas para a mesma coisa, o conserto tem que passar pelas duas — ou o
  código que responde tem que ser um só.
- **O que o NFKD não separa.** Normalizar tirando acento resolve "Rós" →
  "ros" e NÃO resolve o æ de "Ágætis byrjun": ele não é uma composição, é uma
  letra, e a limpeza o trocava por um espaço — "ag tis byrjun" contra
  "agaetis byrjun". Vale para ø, œ, ð, þ, ß e ł. Quem compara nome de disco
  ou de artista precisa da tabela à mão.
- **Um botão que se chama "examinar" tem que mostrar o que tem dentro.** O
  `[enter]` da loja abria um cartão com capa, ano e qualidade — tudo que já
  estava no quadradinho da grade. O que se examina num disco é a ORDEM dele,
  e o Qobuz manda as faixas de graça no `get_album_meta`. Os lados saem do
  mesmo `_build_sides` da estante: uma segunda implementação diria "2 lados"
  na loja e "4" depois de baixar, sobre o mesmo disco.

---

## 5. O tom

Comentário explica **por quê**, não o que. O código já diz o que faz; o que
se perde é o motivo — e o motivo quase sempre é um defeito que já aconteceu.
Quando consertar algo não óbvio, escreva o sintoma no comentário: é isso que
impede o conserto de ser desfeito por engano seis meses depois.

Texto que o usuário vê é em português. Comentário de código acompanha o
arquivo em que está.

## 5.5 A lei do desenho do vinil — NÃO É REALISMO

> **O vinil existe para tornar ouvir música digital menos chato, dando a
> SENSação analógica. O desenho é irmão do scope: luz viva no escuro.
> NUNCA realismo.**

Isto já custou semanas de volta e vai custar de novo se esquecido. Toda vez
que alguém (IA inclusive) tentou desenhar o deck "como um toca-discos de
verdade" — madeira, prafuso, braço de metal com contrapeso, sala com poeira
— o resultado foi reprovado na hora: parecia app de um dólar. O que o usuário
quer:

- **O RITUAL é o analógico** — cerimônia (spinup→cue→drop), raio é tempo,
  sulco conta faixa, agulha anda pelo lado, virar o disco. Isso é sagrado e
  não muda.
- **O DESENHO é fosforo, não foto** — disco de luz flutuando no quase-preto,
  feixe âmbar na agulha pulsando, faíscas na gota da agulha (o `crackle` do
  Deck EXISTE e deve ser desenhado), halo respirando atrás do disco, bloom
  no que é claro, grão sutil. Paleta: preto frio + âmbar como ÚNICA cor
  viva (a mesma lei do vinyl.py: âmbar contrasta, não compete).
- **Proibido**: madeira/prateleira/plinto de móvel, parafuso, sala, poeira
  de ambiente, braço de metal com contrapeso desenhado, sombra de contato
  "física", qualquer coisa que exista numa foto de toca-discos.
- O mesmo vale para o Android (`android/app/.../VinylRenderer.kt`): sem
  plinto, sem sala — o fundo é o halo do próprio disco.

Quando quiser "melhorar o visual", a direção é SEMPRE: mais vida, mais
reação ao som, mais luz com propósito — nunca mais realismo.

## 6. Mudanças Recentes e Pendências

- **Bit-perfect audio:** PipeWire was resampling everything to 48kHz because the audio device was being held open. Reduced `session.suspend-timeout-seconds` to 1 second in `airootfs/etc/wireplumber/wireplumber.conf.d/51-stylus-alsa.conf` to encourage bit-perfect playback.
- **`stylus-deck` sync:** Repository version of `stylus-deck` was outdated and missing fixes, causing playback issues. Synced it with the working local installation.

### Nesta leva (visual e defeitos, tudo commitado)
- **A luz da AGORA era um quadrado preto.** Ver a lição do `set_alpha(None)`
  na §4 — é a mais cara desta leva e a que mais parece inofensiva no código.
- **O braço do deck virou o FACHO (§5.5).** Saíram tubo de alumínio em nove
  cópias, contrapeso em barril, cabeçote, gimbal e o berço em U; a agulha é
  uma cruz curta e quente, o corpo do braço começa a 38% do caminho e quase
  toda a luz mora na ponta; levantado, apaga. O `stylus_xy` não mudou —
  **o ritual é o mesmo**, o material é que deixou de ser metal. E saíram as
  três poeiras de ambiente (uma aparecia; duas nunca desenharam nada).
- **A ESTANTE diz qual disco está no prato:** halo âmbar atrás da capa,
  respirando com o nível do áudio (piso de 110 para não sumir no silêncio
  nem em máquina sem PortAudio), e o nome em âmbar. O halo vai numa passada
  ANTES de todas as capas — desenhado junto com a sua, ele tingia a arte do
  vizinho da esquerda.
- **Três telas desenhavam fora do monitor** e o teste olhava só o eixo
  vertical: a grade dos JOGOS (largura fixa de 940 px num corpo de 794, em
  1024), as duas últimas dicas do rodapé da AGORA em 1280, e o veredito do
  SINAL. O `hint` agora perde dicas INTEIRAS em vez de vazar ou cortar um
  atalho pela metade.
- **`audio_live` quebrava a interface inteira** numa máquina sem
  python-pyaudio: o construtor chamava `np.zeros()` duas linhas antes de
  conferir se o numpy existe, e o `audio_level()` roda em todo quadro.
- **O teste do deck** morria num IndexError quando o álbum não tinha duração
  (isto é: em toda máquina sem ffprobe). Agora diz o que falta e fecha a
  contagem.

### Segunda leva (a pedido: playlist sorteada, Qobuz, visual)
- **Embaralhar e repetir passaram a existir de verdade** — ver a lição na §4.
  `[s]` manda `playlist-shuffle`/`playlist-unshuffle` (o segundo devolve a
  ORDEM DO DISCO, não outro embaralhamento), `[R]` cicla `loop-file` →
  `loop-playlist`. Sem tocador, nada é prometido. Embaralhar deixou de ser
  guardado no arquivo de gosto: é escolha sobre a LISTA, e a lista some com o
  mpv — disco novo devolve a ordem do disco (`_disco_novo`).
- **Playlist do Qobuz sorteada:** `--sortear` no `qobuz_stream`, `[s]` na
  loja da tela cheia, `Alt+s` na grade do rofi. Um DISCO recusa, com recado.
- **A assinatura do Qobuz se renova sozinha** (ver a §4). O `stylus-deck`
  também deixou de retomar uma lista sorteada de onde parou: o índice
  continua valendo, a música por trás dele não.
- **O espectro da AGORA virou um anel no aro do disco**, no lugar da coluna
  de vinte e quatro caixinhas ao lado da capa. Raio = espectro, grave no
  alto, espelhado nos dois lados; parado é uma circunferência.
- **A pilha ganhou ordem:** `[e]` embaralha, `←`/`→` sobem e descem o disco.
- **A AJUSTES ganhou linha de dicas** (era a única sem), o `T.passos` passou
  a desenhar `[c]` como TECLA e não como colchete literal, e a estante passou
  a anunciar o `[r]` (sorteia) e o `[f]` (favorito), que existiam desde
  sempre e não apareciam em lugar nenhum.
- **O `track_index_for` passou a preferir o CAMINHO ao número também sob
  mpv.** Embaralhar reordena a lista, e o `playlist-pos` deixa de ser a faixa
  do disco: o nome na AGORA, o LADO, o "vira em 6 min", a agulha no sulco e o
  índice da agulha.tsv saíam todos errados juntos. O número continua sendo a
  resposta quando o caminho não casa (disco da rede reassinado).
- **O `Nx` do diário vinha da estante**, que conta uma vez na varredura: a
  linha mais nova da tela com o número mais velho dela. E como a fileira de
  capas "OS QUE VOLTAM" filtra por esse número, ela não desenhava NADA — meia
  página faltando sem aviso. Agora a contagem sai do registro que a própria
  tela acabou de ler.

### Terceira leva (defeitos que o usuário viu, e o visual da AGORA)
- **Playlist do Qobuz quebrava a AGORA** (lado sem rótulo — ver a §4), a loja
  parava nos **100 primeiros favoritos** (agora pagina de 100 em 100 até o
  total, teto em STYLUS_QOBUZ_FAVORITOS) e a busca subiu de 30 para 100.
- **Os lados e os discos** passaram a bater com o objeto: 45 min = 2 lados,
  74 = 4, 90 = 4 (era 5). O `Album.discos` existe e a AGORA escreve
  "DISCO 2 · LADO C" — com a folga MEDIDA, que é a lição de sempre.
- **O disco da AGORA SAI da capa** em vez de ser um aro atrás dela: sai pela
  esquerda, o bloco inteiro (saliência + capa + coluna) é que se centra, a
  lombada da capa foi para o outro lado (o disco estava saindo por dentro da
  costura), a agulha aparece no sulco em que está (o raio é o tempo), e o
  disco PÁRA quando a música pára — o ângulo acumula em vez de ser lido do
  relógio.
- **O deck ganhou voz**: "LADO A acabou — vire o disco para o LADO B" em
  ALARM, "PRIMEIRA VEZ" quando a agulha desce, o nome da faixa no canto.
- **A PILHA mede o compromisso**: empilhar lê o disco numa thread e a linha
  passa a dizer "45 min · 2 lados", com o total da noite no rodapé — que era
  uma frase escrita atrás de um `if` que nunca foi verdade.

### Quarta leva (o disco na tela toda, e o resto do sistema)
- **A AGORA ganhou `[f]`: o disco ocupando a tela inteira**, sem trilho e sem
  coluna — o deck sem OpenGL, sem venv e sem janela. É a resposta à pergunta
  "por que não jogar fora o deck e pôr tudo no lançador?": quase tudo já
  cabe. O que NÃO cabe é a cerimônia (spinup → cue → drop) e o braço
  descendo, que é o ritual e a §5.5 chama de sagrado. Enquanto isso não
  estiver aqui, o deck continua sendo o lugar dele.
- **O tamanho grande revelou três defeitos do desenho do disco** que só
  existiam nele: o texto caindo fora da tela, os cinco anéis âmbar dos
  intervalos virando curva de nível, e os sessenta sulcos FIXOS virando alvo
  de tiro. Ver a lição do número fixo na §4.
- **A agulha ganhou o sulco em que anda**, aceso fraco, com o rastro do
  pedaço que acabou de passar — em segmentos, porque pontos com o
  espaçamento do arco leem como tracejado de desenho técnico.
- **Quatro telas do lançador paravam de usar a tela na metade dela** (JOGOS,
  AJUSTES, DIÁRIO, ESTANTE). Mesma lição.
- **A ESTANTE tinha QUATRO respostas para "o que está tocando"** na mesma
  tela — o cartão do trilho, o halo atrás da capa, o nome em âmbar e uma
  tarja no rodapé que ainda anunciava um atalho errado ("enter = ver o
  disco", quando ENTER ali PÕE o disco). A tarja saiu.
- **A barra e o KDE tinham peça escrita e nunca desenhada**, e o `check.sh`
  ganhou duas conferências novas para isso: todo `[module/…]` da polybar tem
  que estar numa linha `modules-*`, e as 18 cores do Konsole têm que ser as
  do alacritty.
- **A paleta do deck era o oposto da lei do desenho, escrito com todas as
  letras.** A seção se chamava "vinyl is plastic, not phosphor" e mandava
  especular BRANCO, sulcos cinzas QUENTES e intervalos QUASE-BRANCOS — a
  §5.5 pela metade: o braço tinha virado luz meses antes e o disco, que
  ocupa a tela, tinha ficado para trás. Agora o corpo é preto FRIO, o brilho
  é a luz âmbar da própria coisa (não uma lâmpada branca fora de quadro), o
  sulco à frente da agulha é grafite frio e atrás dela fica aceso, e os
  intervalos são o mesmo âmbar do `_INTERVALOS` da tela AGORA. O `check.sh`
  agora confere a lei em NÚMEROS (o que é luz tem vermelho acima de 1,5× o
  azul; o que é corpo tem o azul acima do vermelho) — porque o jeito de ela
  ser desfeita não é alguém discordando dela, é alguém "melhorando o visual"
  com a primeira foto de toca-discos que achar.
- **O `stylus-switch-kde` escrevia uma segunda versão do GTK** por cima da do
  `/etc/skel`: trocar para o KDE mudava o corpo da letra de 10 para 11 e
  apagava o `gtk-application-prefer-dark-theme`.

### Sexta leva (a cerimônia entrou no lançador)
- **A tela cheia do disco ganhou a CERIMÔNIA** — spinup → cue → drop. O
  prato sai do zero e acelera, a agulha aparece suspensa FORA da borda e
  desce até o sulco, acendendo. Vale nas duas telas da AGORA, não só na
  cheia. Era a única coisa que o deck tinha de próprio depois que a tela
  cheia nasceu; o que sobra de exclusivo dele agora é desenho de GPU (o
  composto CRT, o acumulador aditivo com bloom, o osciloscópio, as marcas de
  uso lidas do envelope) — nada disso é o ritual.
- **Abrir a interface com música já tocando NÃO encena a cerimônia.** Ali o
  disco não foi posto agora, foi encontrado no meio; encenar a descida da
  agulha seria mentira sobre o que aconteceu. É a diferença entre um ritual
  e uma animação de abertura.
- **A varredura de teclado passou a girar entre as fases da cerimônia**, e
  achou de cara uma divisão por zero no rastro do sulco (`passos` valia 0 e
  o laço dividia por ele). Custa nada e cobre os três momentos em que a
  agulha NÃO está onde ela normalmente estaria, que é onde este código erra.

### Décima segunda leva (o disco do celular era um toca-discos desenhado)
- **A §5.5 valia no computador e não no celular**, e ela diz o contrário com
  todas as letras. O `VinylRenderer.kt` estava com a paleta ANTIGA do deck
  inteira — intervalo quase-BRANCO, brilho em cinza neutro (a lâmpada fora de
  quadro), aro de aço — mais um braço de metal em três camadas com cabeçote
  inclinado nos 23°, cápsula, anéis de pivô e berço; poeira de ambiente em
  DOIS lugares (oitenta motas no Kotlin, cinco no shader do fundo); manchas
  roxas e azuis de "névoa"; um PRATO desenhado embaixo do disco; e uma sombra
  de contato preta que num fundo (0.003) não desenhava nada. Agora o braço é
  o facho (a transliteração do `vinyl.tonearm`: corpo a partir de 38%, luz na
  ponta com expoente 2,2, a agulha em cruz curta e quente) e o fundo é o halo
  do próprio disco. **O ritual não mudou** — o pivô, a varredura e o raio
  como tempo são os mesmos.
- É a mesma doença das seis listas de extensão e das cinco de capa: duas
  cópias da decisão em dois lugares derivam, e a que ninguém olha deriva para
  o lado errado — aqui, para a primeira foto de toca-discos. A conferência
  nova lê a paleta do Kotlin em NÚMEROS e recusa `headshell`, `cartridge`,
  `counterweight`, `plinth`, `nebula` e poeira pelo nome, em código.

### Décima primeira leva (o que o usuário viu, e a loja por dentro)
- **A AGORA:** o disco estava a 0,56 da capa — o centro dele para FORA dela,
  o que lê como duas coisas lado a lado. Com 0,44 o selo encosta na beirada e
  os dois viram um objeto só. E o nome do disco deixou de ser cortado em
  corpo 56 ("Lift Your Ski…"): escolhe o maior corpo que caiba e cai para
  duas linhas, com o ano e o LADO saindo do FIM do nome.
- **A tela cheia travava no B do controle** (§4), o fundo desfocado esticava
  a capa (§4), e ela ganhou a LETRA no tempo: a linha que está sendo cantada
  em lavanda e a seguinte apagada embaixo. Havia ~3000 .lrc na coleção lidos
  só pelo módulo de trinta e dois caracteres da barra.
- **A loja:** o `[enter]` passou a mostrar a ordem do disco em colunas — uma
  por LADO, com a duração de cada uma — pelo `stylus qobuz faixas`, que é
  novo; os favoritos passaram a vir TODOS (§4); e cada disco que você já tem
  leva uma tarja "na estante", que era a primeira pergunta de quem abre uma
  loja.
- **A tela de arranque existia e nunca foi vista**: nada escolhia o tema do
  plymouth. Junto, ela estava em verde e com a agulha azul — e o `check.sh`
  aprendeu a ler cor escrita em fração.
- **O `stylus-update` não levava o GRUB, o plymouth nem o login novos**: duas
  listas escritas à mão (branding-sync e sync.sh) tinham derivado.
- **O `Alt+s` da estante do rofi só fechava a estante**, o `Mod+Shift+O` (que
  sorteia um disco) não punha disco nenhum, e o `stylus check` não olhava
  para a única coisa que a pessoa vê o dia inteiro: a capa.
- Conferências novas: a tecla do rofi sem destino, o sorteio rodando de
  verdade, o tema nunca escolhido, a paleta em fração, a estante que a
  atualização não leva, o `chown -R` na casa inteira, o aviso de virar o
  disco durando menos que o do dunst, a maiúscula que promete Shift, o rodapé
  que anuncia tecla que a seção ignora, a loja mostrando todos os favoritos,
  o fundo que não estica e o "já está na estante".

### Décima leva (a outra metade da coleção, e as listas que discordavam)
- **A metade que mora no celular:** faixa com nome repetido nunca era
  sincronizada, o que você ouviu no celular não chegava à memória da coleção,
  `--deep` era aceito e nunca lido, o `remote_root` varria o aparelho inteiro
  em toda execução, duas playlists de mesmo nome viravam uma só lá, e montar
  o celular de novo apagava a senha do WebDAV. Ver as lições na §4.
- **A capa vinda do Windows.** Cinco listas de nome de capa, duas delas
  comparando maiúscula. Agora é o `vinyl.find_cover`, e o `check.sh` recusa a
  sexta cópia — lendo só linha de código, porque a versão anterior desta
  família casava com o próprio comentário que a explicava.
- **As duas lojas eram medidas vazias**, e com disco dentro se sobrepunham em
  quatro lugares. O teste agora enche as duas antes da varredura de teclado e
  da medição, e a estante de mentira ganhou dois discos de nome comprido —
  foi assim que apareceu o "posto há 11 meses" por baixo do nome do disco no
  DIÁRIO.
- **A configuração do STYLUS voltou a morar num lugar só** (§4), e o `stylus
  audio` passou a enxergar o tocador do sistema.
- **Estado morto** no Deck, no ritual, no lançador e no cache de miniaturas.
- **Os atalhos:** o `Mod+Shift+O`, que sorteia um disco, não estava escrito em
  lugar nenhum; e o KDE deixou de contradizer o i3 em quatro teclas.
- Conferências novas: o plano de sincronia, o registro do celular, a senha do
  WebDAV, a capa (onze casos), a sexta lista de capa, o caminho do sinal, a
  configuração fora do lugar, o estado morto, o atalho não documentado e a
  mesma tecla nos dois modos.

### Nona leva (texto, custo e o celular)
- **"1 faixas" em quinze lugares**, e o `ha_quanto` com o mesmo defeito em
  três das cinco frases.
- **Sortear um disco lia a coleção inteira** — ver a lição na §4. Junto:
  "monta uma noite" varria a estante três vezes para escolher três discos.
- **O celular repartia o MESMO disco de um jeito diferente do computador**
  (teto de 22 min contra 26, sem equilíbrio e sem a regra do par). O
  `buildSides` do VinylActivity.kt agora é a transliteração do
  `Album._build_sides`, conferida contra ele em 192 formas de disco — nada
  neste repositório compila o app do celular, então a lógica foi provada
  traduzindo o Kotlin de volta para Python.
- **Numa playlist, o deck dizia "CONTÍNUO acabou — agora o CONTÍNUO"**: o
  mesmo lado duas vezes, porque num disco de um lado só o `i` e o `i-1` são
  o mesmo.
- Conferências novas: o plural, o custo do sorteio, o celular, e as quatro
  de hoje passaram a PULAR onde falta dependência em vez de reprovar.

### Oitava leva (o lançador em telas pequenas)
- **Em 1024x600 — painel de carro, mini-PC, monitor velho — quatro telas
  desenhavam fora da tela**: a fileira de ações dos JOGOS 60 px abaixo da
  borda, o bloco inteiro da AGORA saindo pela direita em 800, o veredito do
  SINAL por cima da linha de dicas, e o painel de saída da AJUSTES por cima
  do rodapé. Tudo era número fixo: 120 px por fileira, 132 de passo, 560 de
  coluna, 104 de altura de quadro.
- **E o rodapé da AGORA cruzava com os ícones** de embaralhar/repetir/soneca,
  que são desenhados encostados à direita quase na mesma linha.
- O teste passou a varrer 800x600 e 1024x600, e nos DOIS estados (prato vazio
  e disco no prato) — 11 seções × 7 resoluções × 2 estados.

### Sétima leva (bugs de verdade, achados variando as entradas)
- **90 minutos ainda davam CINCO lados** e uma faixa de uma hora dava "DISCO
  2 · LADO A". Ver as lições na §4.
- **O aviso do fim do lado mandava a coisa errada num disco duplo**, nas três
  telas que o dizem.
- **Nenhuma música de menos de 4 minutos era scroblada, nunca**, e pausar não
  parava o contador. O `get_position`, que responderia isso, existia e nunca
  era chamado.
- **O scrobbler e o botão do fone nunca subiram** na máquina de ninguém.
- **Com o Qobuz tocando, o módulo do disco na barra ficava em branco** — o
  `playing_path` recusava o endereço com um `os.path.isfile`, e o
  `vinyl.resolve_album` trata `http(s)://` desde sempre.
- **As playlists do Qobuz tinham o mesmo teto de 100 dos favoritos**, escrito
  na linha de baixo do mesmo arquivo.
- **Seis listas de extensão de áudio**, e o extrator de capas só lia FLAC e
  MP3 (nem abria um .m4a). Junto: o `integrate_album` perguntava "sobrou
  música na origem?" logo antes de um `rmtree` com uma lista sem `.aac`.
- Conferências novas: função órfã, unidade nunca ligada, lista de extensão à
  mão, capa em todo formato, o disco da rede na barra, o scrobble, o gesto
  do fim do lado, e as playlists do Qobuz.

### Quinta leva (o que estava escrito e ninguém via)
- **Duas polybars, uma paleta velha, um terminal que não existe.** Ver as
  lições na §4. Junto: o rofi ainda abria `xfce4-terminal`, consertado no i3
  meses antes com o motivo escrito ao lado.
- **Todo aplicativo Qt escrevia preto sobre preto** e tinha campo de texto
  com fundo âmbar. Os dois arquivos (qt5ct e qt6ct) foram reescritos com a
  ordem dos papéis documentada em cima.
- **O GRUB e o login ganharam a paleta e o âmbar.** O nome STYLUS deixou de
  ser azul na primeira tela da máquina, e o âmbar passa a dizer "é este" na
  conta escolhida, no botão de entrar e na entrada do GRUB que vai subir.
- **O "power LED" do deck nunca desenhou nada** (um `build_strip` de um
  ponto), e era móvel proibido pela §5.5. A marca de onde o LADO começa no
  aro tinha o mesmo defeito e essa foi consertada, porque DIZ alguma coisa.
- **`stylus-mouse` e `stylus-controller` vazavam erro para o journal** com o
  `done < arquivo 2>/dev/null`, que é a lição da §4 sobrando em dois lugares.
- Cinco conferências novas no `check.sh`: todo `[module/…]` da polybar
  desenhado; as 18 cores do Konsole iguais às do alacritty; a §5.5 do disco
  em números; texto legível sobre o fundo no Qt e no KDE; e o ritual
  rodando de verdade.

### Futuras Melhorias
- **Ritual vinyl:** o rework do composto CRT (disco como OBJETO, `u_disc`/
  `u_record` em scope.py) e o braço em luz estão no código; falta VER na
  máquina e afinar ganho. O `deck/tools/vinyl_preview.py` mostra a
  composição sem GL e é o jeito barato de conferir antes.
- **O disco do deck virou luz** (era o item grande desta lista). Falta VER na
  máquina, com o acumulador aditivo e o bloom, e afinar o ganho — o
  `vinyl_preview.py` aproxima a composição e a cor, não o brilho.
- **Missing commands:** conferir se algum comando existe na instalação local
  e não no repositório.
