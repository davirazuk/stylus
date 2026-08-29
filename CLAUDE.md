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
- **Folga fixa entre dois textos na mesma linha sempre quebra na máquina do
  outro.** O `- 300` reservado para o valor à direita não cabia o valor mais
  largo, e o nome do aparelho entrava por cima — só em quem tem placa de nome
  comprido. Meça com `T.largura`. O `test_ui.py` espiona todo `T.text` e
  reclama de retângulos que se cruzam.

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

### Futuras Melhorias
- **Ritual vinyl:** o rework do composto CRT (disco como OBJETO, `u_disc`/
  `u_record` em scope.py) e o braço em luz estão no código; falta VER na
  máquina e afinar ganho. O `deck/tools/vinyl_preview.py` mostra a
  composição sem GL e é o jeito barato de conferir antes.
- **O resto do vocabulário de "foto" no deck.** A paleta do vinyl.py ainda se
  apresenta como "vinyl is plastic, not phosphor / honest materials: black
  plastic reflects white specular", e o disco é desenhado nessa chave —
  cinzas de plástico, não fósforo. Isso é a §5.5 pela metade: o braço virou
  luz, o disco ainda não. É a próxima decisão de desenho, e é grande.
- **Missing commands:** conferir se algum comando existe na instalação local
  e não no repositório.
