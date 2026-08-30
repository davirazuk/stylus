# STYLUS

Uma distribuição Linux construída em volta de ouvir discos.

A agulha é o único ponto em que um objeto vira som. Tudo aqui existe para
deixar esse ponto o mais curto e o mais deliberado possível.

---

## A ideia

Ouvir música num computador ficou ruim de um jeito específico: a pergunta que
o software te faz é **"qual faixa?"**, e a resposta honesta a essa pergunta,
noventa por cento das vezes, é "sei lá, embaralha". Um disco não faz essa
pergunta. Você escolhe **um objeto**, ele manda por quarenta minutos, e no
meio você tem que levantar e virar.

O STYLUS é essa ideia levada a sério num sistema operacional inteiro:

- **O arquivo toca como foi gravado.** O caminho do áudio é configurado para
  seguir a taxa do arquivo em vez de reamostrar tudo para 48 kHz — que é o
  que uma instalação padrão faz com toda a sua coleção, para sempre, em
  silêncio. E `stylus audio` **mede** isso e te mostra, em vez de prometer.
- **O disco fica na tela enquanto toca.** A tela cheia desenha o LP com os
  sulcos, os intervalos entre as faixas, o braço no raio de agora e a capa
  girando no meio. Raio é tempo: bater o olho diz quanto falta do lado, sem
  número nenhum.
- **A coleção lembra.** Todo disco que você põe é anotado. Os discos que você
  mais ouve acumulam marcas na superfície e as marcas de cada um são dele.
- **Dois modos, como num Steam Deck.** *Modo música* é uma tela cheia com a
  estante em capas, feita para ser usada do sofá e com controle — o
  direcional anda, A põe o disco, B volta, os ombros pulam faixa. *Modo área
  de trabalho* é um i3 completo. Um botão vai de um ao outro.

Não tem suíte de escritório. Nunca vai ter.

---

## O que tem dentro

### Ouvir
| | |
|---|---|
| `stylus` | o que está tocando, e onde no disco |
| `stylus deck [DISCO]` | põe um disco: a cerimônia inteira, na tela toda |
| `stylus record` | sorteia um da estante, puxando para os esquecidos |
| `stylus shelf` | a estante em grade de capas |
| `stylus playlists [NOME]` | as listas `.m3u` da coleção — com o nome, põe |
| `stylus lado` | em que lado do disco você está, e quanto falta |
| `stylus parede` | o papel de parede vira o disco que está tocando |
| `stylus ui` | a tela cheia (é o que o modo música abre) |

### A coleção
| | |
|---|---|
| `stylus library [PASTA]` | onde ela fica (descoberto sozinho na primeira vez) |
| `stylus diary` | o que você pôs, quando, quantas vezes |
| `stylus stats` | o formato da sua escuta: quem volta, em que dia, a que horas |
| `stylus check` | o que está quebrado lá dentro |
| `stylus gaps ARTISTA` | que discos desse artista faltam |
| `stylus lyrics` | procura e grava `.lrc` sincronizado |
| `stylus covers` | `cover.jpg` onde falta |
| `stylus rip` | rasga o CD da gaveta, conferido no AccurateRip |
| `stylus get URL` | baixa e arquiva na estrutura certa |
| `stylus qobuz` | a interface do qobuz-dl, e a fila que arquiva disco por disco |

### As máquinas
| | |
|---|---|
| `stylus phone` | o celular: estado, sincronizar, playlists, scrobbles |
| `stylus webdav` | põe a coleção do celular na estante, sem copiar nada |
| `stylus audio` | o caminho do sinal, medido |
| `stylus app NOME` | Clone Hero, qobuz-dl, Proton-GE, o que não vem em pacote |
| `stylus update` | traz o STYLUS novo do GitHub |
| `stylus mode` | troca entre música e área de trabalho |
| `stylus claude` | o Claude Code, com a fonte do sistema aberta do lado |
| `stylus atalhos` | a lista de atalhos de teclado |
| `stylus instalar` | instala no computador (a partir do pendrive) |

---

## Virar o lado, e a parede

O README abre dizendo que a coisa toda é escolher um objeto, ele mandar por
quarenta minutos e você ter que levantar e virar. A máquina sabia disso — a
barra mostrava "vira em 12 min" — mas ninguém nunca era **avisado** na hora: o
lado acabava, o próximo arquivo entrava, e a diferença entre ouvir um disco e
ouvir uma playlist simplesmente não acontecia. Um contador que só conta não é
um acontecimento.

`stylus lado` diz onde você está agora; o serviço que roda na sessão avisa
quando o lado **vira**, e só para frente — arrastar a barra para trás é
procurar uma faixa, não virar o disco. Quem quiser a coisa inteira liga
`STYLUS_SIDE_PAUSE=1` e o som para no fim do lado, como pararia.

E a agulha fica onde você a deixou. Levantar a agulha e voltar depois não
recomeça o disco da faixa 1 — isso é coisa de tocador de arquivo. O mesmo
serviço anota a posição enquanto toca, e `stylus deck` volta para lá:

```
stylus deck loveless              de onde você parou
stylus deck --recomeçar loveless  do começo
stylus deck --lado B loveless     pelo lado B, que é o de que você gosta
```

Não dá para deixar isso a cargo do `--resume-playback` do mpv: ele guarda a
posição pelo hash do **caminho do arquivo** que estava tocando, então relançar
o disco inteiro faz ele procurar a posição salva da faixa 1 — que quase nunca
é onde você parou. Quem sabe qual faixa é o índice da lista, e esse é nosso.

```
stylus parede            o disco de agora vira o papel de parede
stylus parede --sozinho  e continua virando, a cada disco novo
stylus parede --restaurar
```

O desenho não é a capa: vem da **intensidade medida** do álbum, faixa por
faixa. Dois discos diferentes dão duas paredes diferentes, e a sua não existe
na máquina de mais ninguém. Medir custa — o primeiro disco leva de segundos a
minutos — então o resultado fica em cache e o segundo login é instantâneo.
Desligado até você pedir: papel de parede é seu.

---

## A noite

Três coisas para a hora em que a casa fica quieta, todas na tela cheia
(a seção **AGORA**):

```
[t]         a soneca: 15 → 30 → 45 → 60 → 90 minutos → FIM DO LADO
[Shift+G]   a trava do gato
[f]         o disco ocupando a tela inteira
```

A **soneca** não corta o som: ele desce em vinte segundos e a tela escurece
junto, porque do outro lado do quarto a música sumindo com a tela acesa
parece defeito. E a opção que interessa é o **fim do lado** — ninguém
adormece no meio de um lado por vontade própria; o lado acaba, e é aí que a
agulha levanta.

A **trava do gato** é da tela, não do sistema: a música segue, o disco
continua girando por baixo de um véu, e nenhuma tecla, clique ou botão de
controle atravessa. Destrava segurando **ctrl+alt+esc por um segundo e
meio** — os três juntos e por tempo, porque um gato deitado no teclado
segura teclas, e às vezes muitas, mas não segura estas três. De manhã a tela
diz há quanto tempo está travada e quantas vezes ele tentou.

---

## Playlists

O sistema escrevia `.m3u` desde sempre (`stylus suggest` escreve por gênero,
`stylus get` acrescenta o que chega) e não sabia tocar nenhuma. Agora sabe:

```
stylus playlists                       o que existe, e quantas faixas
stylus playlists "Novidades 2026-08"   põe aquela
stylus playlists --limpar              tira as faixas cujo arquivo sumiu
stylus deck "Shoegaze & Dreampop"      idem — o nome acha lista antes de disco
```

Na estante de tela cheia, o `[o]` cicla a ordem até **listas**. Elas ficam
fora da grade de discos de propósito: uma lista com a capa do primeiro álbum
dela se disfarçaria de disco.

Uma playlist **não é um disco**, e a diferença aparece: ela entra como um
lado só e contínuo, sem "vire o disco". O aviso de virar o lado é verdade
sobre um objeto que tem dois lados; numa lista de duzentas faixas viraria um
alarme a cada vinte minutos.

E o caminho de volta: na **PILHA**, o `[Shift+G]` guarda a noite que você
empilhou como uma lista na coleção.

---

## O celular

A coleção não está "no PC". Está no PC e no celular, e a parte difícil nunca
foi copiar arquivo — é os dois lados concordarem sobre qual cópia é a melhor
sem ter que ler as duas.

`stylus phone` mantém um **manifesto** deste lado: comparar passa a ser um
`find` só do outro lado contra um JSON daqui. Ele também:

- **descobre onde a música está** no celular em vez de chutar `/sdcard/Music`
  (que num aparelho de verdade costuma ter só toque de despertador);
- **casa bibliotecas organizadas de formas diferentes** — plana de um lado,
  `Artista/Álbum` do outro — comparando primeiro o caminho e depois o nome;
- **leva as playlists junto**, reescrevendo os caminhos, que é a coisa que
  nenhuma ferramenta faz e que dói toda vez;
- **junta o que você ouviu no celular** à memória da coleção, para o desgaste
  dos discos refletir a escuta inteira e não só metade dela;
- funciona **por wifi**, não só por cabo.

### E quando não se quer copiar

`stylus phone` **copia** — é para a música ficar nos dois lados. Mas quem tem
200 GB no celular e 60 no computador não quer copiar: quer pôr para tocar.

`stylus webdav` monta o servidor WebDAV do celular como uma pasta, e os discos
que estão lá aparecem **na mesma estante** que os de casa — sem duplicar um
arquivo sequer.

```
stylus webdav ligar http://192.168.0.10:8080/   # o endereço que o app mostra
stylus webdav sozinho                           # e a cada login
```

Montado como **só leitura**: pôr um disco não escreve nada, e um `rm`
distraído numa pasta montada apagaria a música do celular de verdade. Para
mandar arquivo, `stylus phone`, que sabe o que está fazendo.

Por baixo é o `rclone`, que já estava aqui — monta em espaço de usuário, sem
root, sem linha no `/etc/fstab`, e guarda a senha ofuscada em vez de em texto
puro num arquivo de sistema. Um servidor num celular muda de IP e cai o tempo
todo; nada disso merece root.

---

## O caminho do sinal

`stylus audio` mede, em vez de prometer. Ele responde três perguntas, nessa
ordem, porque é essa a ordem em que elas importam: em que taxa o grafo está
rodando agora, o arquivo que está tocando tem essa taxa, e — se não tem —
**quem** está segurando o grafo na outra. A terceira é a única acionável: um
grafo compartilhado toca numa taxa por vez, e enquanto aquela aba do navegador
estiver aberta em 48 kHz não há configuração no mundo que salve o seu FLAC de
44,1.

Faltava a outra metade. Tudo isso mede do PipeWire **para a frente**, e o
lugar mais fácil de estragar o som fica antes dele: o `~/.config/mpv/mpv.conf`.
Uma linha `replaygain=track` herdada de outra máquina normaliza o volume faixa
a faixa — que é precisamente o que uma playlist faz e um disco não — e o
relatório continuaria dizendo "sem conversão". Audível e invisível ao mesmo
tempo.

Então: o `stylus deck` passa `--replaygain=no --af= --volume=100
--audio-samplerate=0` na linha de comando, que **ganha** do arquivo de
configuração, e o `stylus audio` agora pergunta ao mpv que está tocando o que
ele está fazendo de verdade — e aponta as linhas do seu `mpv.conf` que mexem
no caminho, explicando que ali não afetam mas afetam quando você abre o
arquivo com `mpv` na mão.

Um detalhe de quem tem a coleção montada pela rede (o `stylus webdav` põe o
celular na estante): um FLAC de 24/96 lido por FUSE sem leitura adiantada
engasga no meio da faixa, e o sintoma parece defeito de áudio. Quando o disco
está num sistema de arquivos de rede, o tocador ganha vinte segundos de
adiantamento. Local não precisa e não ganha nada.

---

## Encher a estante

```
stylus qobuz              está instalada? no ar? em que porta?
stylus qobuz instalar     instala a interface do qobuz-dl
stylus qobuz abrir        põe no ar e abre no navegador
stylus qobuz fila ARQ     baixa a fila inteira e arquiva disco por disco
```

O arquivo da fila é uma linha por disco:

```
https://open.qobuz.com/album/xxxxx|Talk Talk|Laughing Stock
```

Cada disco é terminado **por inteiro** — baixa, junta os discos duplos numa
pasta só renumerando na sequência, move para `Artista/Álbum`, arruma as tags,
embute a capa, busca a letra, atualiza a playlist mestre — antes de o próximo
começar. Uma queda de energia no meio nunca deixa meio álbum enfiado na
estante, e o que já estava lá é pulado em vez de baixado de novo.

O que a fila pede ao backend vai **explícito**, opção por opção. Parece
excesso de zelo e não é: um pedido pelado faz o backend tratar cada chave
ausente como um `False` de verdade, e um `False` de verdade ganha do
`config.ini` — a fila inteira baixaria sem capa embutida e sem `cover.jpg` em
tamanho cheio, ao contrário do que a configuração manda, em silêncio.

---

## Consertar

```
stylus claude
```

Este sistema é mantido por uma pessoa e um Claude, e até agora o Claude
trabalhava de longe: um contêiner sem placa de som, sem disco e sem tela, onde
dava para ler o código e não dava para ver nada acontecer. Foi assim que o
instalador chegou a formatar o disco para só então descobrir que faltava uma
linha no `pacman.conf`.

`stylus claude` acaba com isso. Ele instala o Claude Code, deixa a **fonte**
do sistema em `~/stylus` — um clone de git seu, para editar — e escreve as
instruções desta máquina em `~/.claude/CLAUDE.md`: onde acaba a fonte e começa
o sistema, o que é seguro olhar, e o que não se faz.

O ciclo é curto:

```
# edite em ~/stylus, e então
~/stylus/tools/check.sh
sudo STYLUS_SOURCE=~/stylus/airootfs /usr/share/stylus/sync.sh
```

Isso aplica **este clone** na máquina, sem passar pelo GitHub. Deu certo,
commit e push; da próxima vez o `stylus update` traz para todo mundo.

A regra que vale aqui, e está escrita nas instruções para não ser esquecida:
**conserta-se a fonte, não a máquina.** Editar `/usr/local/bin` à mão funciona
até o próximo `stylus update`, que copia a fonte por cima e apaga o conserto
sem dizer nada — duas semanas depois o defeito volta e ninguém liga uma coisa
à outra.

Também vem com `/aplicar` (aplica e diz o que reiniciar) e `/diagnostico`
(junta o estado real da máquina antes de qualquer palpite).

---

## Atualizar

```
stylus update
```

Clona este repositório e copia o `airootfs/` por cima do sistema. Qualquer
melhoria empurrada para cá chega na máquina com um comando — sem ISO nova,
sem reinstalar.

**A configuração que você mexeu é sua.** Um arquivo de dotfile diferente do
padrão é **mantido**, e o novo fica ao lado como `.novo`. Copiar por cima em
silêncio é o defeito mais comum de distribuição caseira e é irreversível para
quem não tem backup.

---

## Construir

```
./tools/check.sh     # as verificações, em segundos
./build.sh           # a ISO, em ./out
tools/flash.sh out/stylus-*.iso
```

`check.sh` pega quase tudo que já quebrou este tipo de repositório — nome de
pacote que não existe, link apontando para arquivo renomeado, config do i3
que o i3 recusa, ferramenta que o menu promete e não está lá — em segundos,
contra a meia hora de uma construção.

Numa máquina Arch o `build.sh` usa o `mkarchiso` direto. Em qualquer outra
distribuição ele cai para um contêiner (`podman`), e as conferências passam a
rodar lá dentro — onde o shellcheck, o fish e o pacman existem — em vez de
reprovarem a construção por falta de ferramenta no computador de fora.

### Construir sem computador (pelo celular)

Não dá para construir uma ISO do Arch **no** celular: é preciso montar, fazer
chroot e criar nós de dispositivo, e nem o Termux nem um proot fazem isso sem
root de verdade. O que dá é mandar construir e baixar pronta:

1. No GitHub, aba **Actions** → **Construir a ISO** → **Run workflow**.
2. Uns 30 minutos depois, o arquivo está em **Artifacts**, no fim da página
   da execução — o navegador do celular baixa direto.
3. Para gravar no pendrive pelo próprio celular: **EtchDroid** e um cabo OTG.
   (O `tools/flash.sh` é para quando há um computador; ele recusa disco
   interno de propósito.)

O `.sha256` vai junto, para conferir que o arquivo chegou inteiro.

---

## De onde vem

O maquinário de hardware (instalador, driver de vídeo, mouse, controle,
escala de tela) veio do [IFOS](https://github.com/davirazuk/ifos), a outra
distribuição do mesmo autor, e foi rebatizado. É código testado contra
máquinas quebradas de formas que esta não está; reescrever produziria uma
versão pior.

Tudo que dá identidade ao STYLUS — o disco na tela, a estante, a memória da
coleção, o caminho de áudio, a interface de tela cheia, os dois modos, o
celular — é deste projeto.
