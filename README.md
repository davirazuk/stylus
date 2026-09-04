# vitastylus — tocador de música para PS Vita

Porte do tocador Stylus (PC/Android) para PS Vita: biblioteca local com capas,
estante de álbuns, deck vinil em âmbar sobre quase-preto, playlists,
recomendações e registro de escuta.

**Áudio: MP3, FLAC, Ogg Vorbis, Opus e WAV.** O FLAC sai idêntico ao
original — o teste compara amostra a amostra com o WAV de origem. O Vita
entrega 16 bits e um punhado de taxas, então um FLAC de 96 kHz/24 bits é
reamostrado e reduzido antes de virar som: **o deck diz isso na tela**, em
vez de imprimir a qualidade do arquivo e deixar você achar que ouviu aquilo.

## Instalar

Com o SD2VITA plugado no PC, um comando faz tudo:

```sh
./tools/pro-cartao.sh                 # constrói, confere, copia
./tools/pro-cartao.sh --capas         # e leva as capas que faltam
```

Ele **confere que os PNG do `sce_sys` estão em paleta de 8 bits** antes de
copiar — sem isso o instalador recusa com `0x8010113D` e você só descobre no
aparelho. Também diz onde o app vai procurar música e quanto há lá. Não
encosta em `ux0:tai/` nem no plugin.

Depois, no Vita: instale `ux0:vitastylus.vpk` pelo VitaShell. O `TITLE_ID`
não muda, então instala por cima da versão anterior.

Na mão, se preferir:

1. Copie `build/vitastylus.vpk` para o cartão.
2. Instale pelo VitaShell.
3. Ponha a música em `ux0:music/Artista/Álbum/*.mp3`.

## Onde ele procura a música

Em **todas** estas pastas, não só na primeira que existir:

```
ux0:music                     SD2VITA / cartão principal
ux0:data/vitastylus/music     a pasta do próprio app
uma0:music                    cartão oficial da Sony
imc0:music                    memória interna (modelo 2000)
xmc0:music
```

Se a sua coleção estiver em outro lugar, escreva os caminhos em
`ux0:data/vitastylus/roots.txt`, um por linha (`#` é comentário):

```
# a minha coleção
ux0:MinhasMusicas
uma0:mp3
```

Com esse arquivo presente, só as pastas dele são varridas.

**Se a estante abrir vazia, ela diz por quê** — quais pastas foram tentadas,
quais abriram, quantos arquivos foram vistos e quantos não eram áudio. Não há
mais o caso de "0 discos" sem explicação.

### Organização aceita

| No cartão | Vira |
| --- | --- |
| `Artista/Álbum/01 - Faixa.mp3` | artista + álbum + faixa 1 |
| `Artista/Álbum/CD1/01 Faixa.mp3` | artista = `Artista`, álbum = `CD1` |
| `Álbum/01. Faixa.mp3` | álbum, sem artista |
| `*.mp3` solto na raiz | **um** disco `(sem pasta)` com todas |

O número da faixa sai do nome do arquivo (`NN - `, `NN. `, `NN_`, `NN `) e o
título perde esse número — mas só quando o disco INTEIRO é numerado e a
numeração é densa. `1979.mp3` continua se chamando 1979, e `99 Problems.mp3`
sozinho numa pasta não vira "Problems".

Arquivos que não têm decodificador (`.m4a`, `.wma`, `.ape`…) **aparecem na
estante mesmo assim**, marcados. Escondê-los faria o app dizer "não achei
nada" para quem tem a coleção inteira num formato só.

## Controles

| Botão | Estante | Deck (tocando) | Recs | Playlists |
| --- | --- | --- | --- | --- |
| D-pad | navega (repete se segurar) | ◄► troca faixa · ▲▼ seek ±10 s | navega | navega |
| ✕ / ○ | toca o disco | pausa / recomeça | toca a partir da marcada | toca |
| △ | vai ao que está tocando | volta à estante | estante | estante |
| □ | régua de letras (ir para) | letra ↔ ordem do lado | — | guarda o que toca |
| L1 / R1 | recs / playlists | recs / playlists | ↔ | ↔ |
| Select | alterna sorteio | cicla repetição | — | apaga a lista (2 toques) |
| **R1 + L1** | — | **apaga a tela e continua tocando** | — | — |
| **R1 + □** | — | **soneca** (esmaece 20 s → fim do lado → off) | — | — |
| **R1 + △** | — | **ouvir enquanto joga** | — | — |
| Start | sai | sai | sai | sai |

### Toque

A tela é sensível ao toque e o app inteiro a ignorava.

- **estante**: toque num disco para pôr; arraste de lado para virar a página
- **deck**: toque no disco pausa; arraste a barra para buscar; arraste de
  lado para trocar de faixa
- **recs / playlists**: toque numa linha para tocar dali

## O disco tem LADOS

É a tese do sistema inteiro, e o tocador do Vita não a tinha — um álbum aqui
era uma fila de arquivos, como em qualquer outro tocador.

O deck diz **DISCO 2 · LADO C**, quanto falta para **virar** (não para a
faixa acabar), e no fim do lado o gesto que o objeto pede — que não é o mesmo
nos dois casos:

- lado ímpar → *"vire o disco para o LADO B"*
- lado par de um duplo → *"ponha o DISCO 2, LADO C"* (você levanta e vai até
  a estante)

O corte é a **transliteração** do `Album._build_sides` do desktop, não uma
reinvenção: 45 min = 2 lados, 74 = 4, 90 = 4, e 21 min cabem inteiros num
lado só. O `check.sh` reparte **1887 formas de disco** pelas duas regras e
compara lado a lado, contra o `vinyl.py` de verdade — não contra uma cópia
dele, que derivaria.

## A letra

Um `.lrc` ao lado do arquivo: `[□]` no deck troca a ordem do lado pela letra,
com a linha que está sendo cantada em âmbar. Lê `[offset:±ms]`, aceita
`[00:40]` sem centésimos, e `[00:30][01:00]refrão` — uma linha com dois
momentos, que é como todo refrão de `.lrc` é escrito — vira as duas
aparições.

## Ouvir enquanto joga

**`[R1+△]` no deck** abre a tela que explica isto, e ela detecta se o plugin
está instalado.

O Vita **suspende** qualquer aplicativo que sai da frente — este inclusive —
e isso não é contornável de dentro de um VPK. O **Music Premium**
(cuevavirus) destrava o app **MÚSICA da Sony** para tocar dentro dos jogos;
ele não faz um homebrew qualquer continuar tocando. Um homebrew só tocaria
por trás sendo ele próprio um plugin de kernel, que é outro programa.

O que dá para fazer, e o app faz:

- **`[R1+L1]` apaga a tela e continua tocando.** O OLED é o que come a
  bateria num tocador de música; assim ele toca por horas.
- **O timer de suspensão do Vita é cancelado enquanto toca.** Sem isso o
  aparelho suspendia sozinho depois de alguns minutos sem toque e um álbum
  inteiro nunca chegava ao fim.
- **Ao voltar de um jogo, o app retoma exatamente onde parou**, em pausa.
- A tela do `[R1+△]` mostra a **pasta e a faixa** para você achar o mesmo
  disco no app Música — é a mesma `ux0:music`.

## Dados do app

Tudo em `ux0:data/vitastylus/` — criado no primeiro arranque:

- `roots.txt` — as suas pastas de música (opcional)
- `playlists/*.m3u` — as listas
- `history.txt` — contagem por faixa, base das recomendações
- `last_session` — faixa e posição para continuar onde parou
- `stylus-scrobbles.tsv` — registro de escuta, MESMO formato do Android do
  Stylus: `timestamp<TAB>artista<TAB>álbum<TAB>pasta`. No PC, `stylus phone
  scrobbles` junta esse arquivo à memória da coleção.

## Build

```sh
export VITASDK=$HOME/vitasdk
export PATH=$VITASDK/bin:$PATH
./build.sh          # saída: build/vitastylus.vpk
```

Pacotes necessários: `libvita2d`, `vitaShaRK`, `freetype`, `libpng`,
`libjpeg-turbo`, `zlib`, `mpg123`, `SDL2`.

A arte (ícone e LiveArea) é gerada por `tools/make_art.py` — sem PIL, só zlib.
Rode se mexer no desenho; o `sce_sys/` fica versionado.

## Conferências

```sh
./tools/check.sh
```

Roda em qualquer máquina com `gcc`, sem VitaSDK e sem Vita. Cobre:

- **os decodificadores, contra ÁUDIO DE VERDADE** (`tools/decoder_test.c`):
  gera um sinal conhecido, codifica em FLAC/Ogg/Opus/MP3/WAV e decodifica de
  volta. Do FLAC e do WAV exige as amostras **idênticas**, uma a uma — um
  decodificador que troque os canais, erre o intercalado ou perca um bloco
  reprova aqui e passaria em qualquer teste que só olhasse "tocou alguma
  coisa". Também exige que depois de um seek venha o áudio **daquele ponto**;
- **o corte dos LADOS contra o desktop**, 1887 formas de disco;
- **o núcleo, exercitado de verdade** (`tools/host_test.c`): uma coleção de
  mentira é montada em disco e varrida — ordem das faixas, número tirado do
  nome, faixas soltas na raiz, dedup de raízes, `roots.txt`, os lados, a
  letra, e as duas frases diferentes de "não achei nada";
- **a geometria das telas** (`src/ui_layout.c` é puro de propósito): toda a
  grade, o disco, a coluna de texto e as listas medidos contra a tela, em
  várias resoluções. É o defeito mais repetido deste projeto e o único jeito
  de pegá-lo sem abrir janela;
- a paleta pelo `RGBA8` (ver abaixo), tecla prometida no rodapé e não tratada,
  função órfã, lista de extensão duplicada, caminho montado à mão, heap
  declarado.

Cada uma foi medida com o defeito posto de propósito — e uma delas passou
verde na primeira tentativa: o teste do seek procurava com o decodificador
recém-aberto, quando o defeito só existe depois de ter LIDO alguma coisa.
Corrigido, os nove sabotados ficam vermelhos.

## Coisas que já custaram tempo

- **O vita2d empacota ABGR, não ARGB.** A paleta estava escrita à mão em
  hexadecimal como se fosse ARGB: `0xFFFFAA28`, o âmbar do projeto inteiro,
  saía no aparelho como (40,170,255) — **azul-celeste** — e o azul frio do
  halo saía marrom. A §5.5 ao contrário em todas as telas, e invisível na
  leitura: os números "parecem" âmbar. Agora tudo passa pelo `RGBA8`.
- **A ordenação das faixas invertia o álbum inteiro.** A insertion sort
  comparava o número já normalizado para 0 contra o `-1` cru do outro lado: a
  condição de parada nunca dava verdadeira. Todo disco tocava de trás para a
  frente, sem erro nenhum.
- **`find_album` exigia `key[0]`**, então a pasta RAIZ nunca casava: cada
  faixa solta em `ux0:music/` virava um álbum só dela.
- **A posição era sempre 00:00.** `done / (canais*2 * taxa)` em inteiros é
  `8192 / 176400`, que é ZERO. O tempo parado, a agulha na borda, a barra
  vazia e o ponto de continuação sempre no começo.
- **`ux0:data/vitastylus` nunca era criado.** O `mkdir` cru não cria pai, e
  ninguém criava esse: histórico, scrobble e continuação abriam arquivo numa
  pasta inexistente, o `fopen` devolvia NULL e cada função voltava calada.
  Nada do que a pessoa ouviu era guardado, sem uma linha de erro.
- **`album_load_cover` não era chamado por ninguém.** A função existia, estava
  certa, e nenhuma capa era carregada em lugar nenhum — o `cover_to_tex`
  sempre via `NULL`. É a família do `set_text` do deck: quando achar um helper
  que ninguém chama, desconfie de um recurso inteiro faltando.
- **A capa era decodificada a cada QUADRO.** Nove JPEGs abertos e jogados fora
  sessenta vezes por segundo na estante, onze nas recomendações. Agora há
  cache, e no máximo uma decodificação por quadro.
- **O Vita não tem L2/R2.** "Apagar playlist" estava em `[R2]`, escrito no
  rodapé, e o bit nunca chega pelo `sceCtrlPeekBufferPositive`. A tecla não
  existia em aparelho nenhum.
- **Cards de 296×330 numa tela de 544.** Três fileiras somavam 1042 px: as de
  baixo eram desenhadas fora do monitor enquanto a paginação contava com nove
  visíveis, e a seleção podia parar numa fileira invisível.
- **O seek não esvaziava o anel.** O mpg123 pulava, mas até seis segundos de
  PCM velho continuavam na fila: a música só obedecia depois, o que lê como
  "o seek não funciona".
- **Uma faixa que não abre parava a sessão inteira.** Um `.flac` no meio de um
  álbum, ou um arquivo corrompido, e tudo parava em silêncio. Agora o player
  anda para a seguinte, no máximo uma volta, e o deck DIZ o que aconteceu.
- **`ux0:music/` com barra montava `ux0:music//Artista`.** O `sceIoGetstat`
  recusa barra dupla. Quem monta caminho agora é o `path_join`.
- **O histórico era escrito pela thread de ÁUDIO** enquanto o laço principal
  lia a mesma estrutura para montar as recomendações — realloc de um lado,
  leitura do outro. Agora o callback só enfileira.
- **O heap padrão do homebrew não cabe uma coleção grande.** Cada `Track` são
  ~1,5 KB; 5000 faixas já pedem 8 MB só de estrutura. Sem
  `_newlib_heap_size_user` o `malloc` começa a devolver NULL no meio da
  varredura e a estante fica pela metade, calada.
- **O VPK saía sem ícone e sem LiveArea**: um quadrado em branco no menu do
  Vita, que é a diferença entre "um app" e "um arquivo".
- **O Vita SUSPENDE sozinho depois de alguns minutos sem toque**, e suspenso
  o áudio para: um álbum inteiro nunca chegava ao fim se ninguém encostasse
  no aparelho. Cancelar o timer é uma linha e nada no app a tinha. A TELA,
  ao contrário, deixamos apagar — é um tocador de música, e o OLED é a
  bateria.
- **O painel de toque é 1920×1088, o dobro da tela.** Usar as coordenadas
  cruas põe todo toque no canto superior esquerdo. É o erro que se comete
  uma vez.
- **`[quad]` no deck era um segundo "seek −10 s"**, duplicando o `[baixo]` —
  uma tecla gasta em nada num aparelho que tem poucas.
- **O libFLAC pede `utimensat`, que o newlib do Vita não tem.** Só LEMOS
  FLAC, mas o escritor de metadados mora no mesmo `.a` e o linker estático
  cobra o símbolo. O stub devolve erro em vez de fingir sucesso.
- **`TRACKNUMBER=7/12` vira faixa 712** sem parar no primeiro não-dígito, e
  `7/12` é a forma mais comum de escrever isso.
- **O `ov_read` e o `op_read` devolvem MENOS do que se pediu sem que isso
  seja fim de faixa** — um pacote por vez. Tratar "menos que o pedido" como
  fim corta a música no primeiro pacote curto.
- **Procurar num FLAC sem esvaziar o buffer** faz o PCM de antes do salto
  tocar depois dele. E o teste que existia para pegar isso passava verde,
  porque procurava com o decodificador recém-aberto — sem nada no buffer não
  há o que ficar velho.

## A lei do desenho (§5.5)

O vinil existe para tornar ouvir música digital menos chato dando a SENSAÇÃO
analógica. O desenho é fósforo, não foto: disco de luz no quase-preto, âmbar
como única cor viva, o braço é o FACHO (o corpo começa a 38% do caminho, quase
toda a luz na ponta, levantado apaga). **Nada de** madeira, plinto, parafuso,
contrapeso, cabeçote, sala ou poeira de ambiente. O `check.sh` recusa essas
palavras no código do desenho e confere a paleta em números.

## O que ainda não existe

- [ ] Teste em aparelho de verdade. O VPK é construído e conferido no host —
      cor, geometria, decodificação amostra a amostra, atalhos, formato dos
      ícones. **Nada disso foi visto num Vita**, e a fonte do sistema não é a
      que o preview usa.
- [ ] M4A/AAC e WMA — aparecem na estante, marcados, sem decodificador
- [ ] Qobuz **no aparelho**. O PC baixa (ver "Qobuz"); transmitir do Vita
      exigiria HTTPS no aparelho, que o `net.c` nunca validou em hardware.
- [ ] Fila do last.fm — existiu numa linha paralela deste projeto e não veio
      na fusão: depende de rede no Vita, que segue sem validação.

Uma coisa que ESTE arquivo afirmava e não se sustenta: que o áudio em segundo
plano deste app é "limite de plataforma, não de código". Isso foi escrito
quando o app **não pedia a porta BGM** — e sem pedir, nenhum plugin de kernel
teria como manter processo nenhum vivo. Hoje ele pede, mantém a taxa dentro
do teto, e o autor do MusicPremium anuncia "background music play for **any**
game or application", citando VitaShell e ElevenMPV, que são homebrew.
Não está provado que funciona; está provado que a conclusão anterior vinha
de um teste que não podia dar outro resultado. A tela "ouvir enquanto joga"
mostra as duas condições medidas e manda experimentar.

## Áudio em segundo plano (ouvir dentro de um jogo)

Duas coisas precisam valer, e uma sem a outra não funciona:

1. **O app pede a porta BGM** no arranque (`sceAppMgrAcquireBgmPort`) e a
   devolve na saída — presa, a próxima abertura leva `BGM_PORT_BUSY`.
2. **A taxa de saída cabe em 47999 Hz.** Quem escolhe o TIPO da porta é o
   SDL2, e ele decide pela taxa — lido do binário do vdpm (SDL 2.32.8):
   `cmp freq,#47999 ; movgt r0,#0 (MAIN) ; movle r0,#1 (BGM)`. Acima disso a
   porta é MAIN, e MAIN o plugin de CFW não mantém viva.

   Numa varredura do cartão, **996 de 3728 arquivos eram 48 kHz** — 27% da
   coleção perdia o segundo plano em silêncio.

   Hoje **todo formato** cabe: o MP3 pede a reamostragem ao mpg123 na
   abertura, e FLAC, Vorbis, Opus e WAV passam por um sinc janelado no
   `decoder.c`. A saída é sempre uma taxa que o `sceAudioOut` aceita (96 kHz
   não é uma delas), e é por isso que o `rate_out` da tela voltou a ser
   verdade: antes ele repetia o que **pedimos** ao SDL, não o que o aparelho
   recebeu.

O deck mostra o resultado **cruzando as duas** — "2º plano: sim/não" na linha
do sinal —, porque uma sozinha seria promessa e não medida.

Falta o plugin de CFW, que só ele impede a suspensão do processo:

```sh
./tools/musicpremium.sh [/caminho/do/cartao]
```

Baixa do host do autor, confere o sha256, confere que é um módulo do Vita e
põe em `ux0:tai/`. O último passo é no aparelho (a config do taiHEN mora em
`ur0:`, memória interna) — o script imprime como.

## Qobuz

O Vita não fala com o Qobuz; o PC fala, e a ponte é o download.
`track/getFileUrl` devolve uma URL HTTPS comum, assinada, válida ~1h — o
`private_key` assina o PEDIDO, ele não criptografa o áudio.

```sh
./tools/qobuz-vita.py buscar radiohead in rainbows
./tools/qobuz-vita.py baixar ID                     # MP3 320 -> cartão
./tools/qobuz-vita.py baixar ID --formato flac      # FLAC 16/44,1
./tools/qobuz-vita.py espaco                        # quanto o cartão já usa
```

Padrão MP3, com teto de 1 GB por download (`--limite-gb`, `--forcar`): estima
o tamanho antes, confere o espaço livre e, em FLAC, diz quantas vezes menor
seria em MP3. **`--formato flac` (fmt 6) é o melhor caso: lossless E segura o
2º plano.** Hi-res toca, mas perde o segundo plano.

Para preparar música que já é sua, `./tools/para-vita.py PASTA` (converte
para MP3 44,1k com capa embutida).

### As capas que o cartão perdeu

A cópia da música que está no cartão **perdeu a arte embutida**: a coleção do
PC tem capa em 339 de 405 álbuns; a do cartão, em 4. Quem copiou descartou os
quadros APIC. Sem capa a estante vira uma parede de discos iguais, que é o
oposto do que este tocador é.

Recopiar tudo seriam horas e gigabytes. Mas capa é **metadado** — dá para
levá-la sem tocar no áudio:

```sh
./tools/para-vita.py --capas-de ~/staging-vita/vita-mp3 \
                     --destino  /run/media/davirazuk/VITASD/music
```

Casa os álbuns pelo nome da pasta, pula os que já têm capa e escreve só o
APIC. Conferido: depois do transplante o PCM decodificado é **idêntico** ao
do arquivo original (sha256 igual), e a estante passa a mostrar a arte. Use
`--dry-run` antes para ver o que ele faria.

## Ver a UI sem o Vita

```sh
./tools/preview.sh [raiz-de-musica] [dir-de-saida]
```

Compila o `ui.c` de verdade contra um shim das primitivas do vita2d
(`tests/hostgfx/`) e grava as telas em PNG. É aproximação, não emulação: a
cor e a geometria são fiéis, a fonte é Noto Sans e não a PVF do sistema —
as ressalvas estão no topo de `tests/hostgfx/vita2d_host.c`.

## Ícones da LiveArea

`./tools/icons.sh` gera `sce_sys/` a partir de `assets/*.svg`. **Atenção ao
formato**: o instalador recusa com `0x8010113D`/`0x9010113d` PNG que não seja
de PALETA de 8 bits. A doc de referência manda passar por `ffmpeg -pix_fmt
ya8` — mas `ya8` é CINZA, e seguir isso ao pé da letra instala um ícone sem
cor nenhuma. `pngquant` sozinho indexa E preserva a cor; é o que fazemos.
