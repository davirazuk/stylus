# vitastylus — tocador de música para PS Vita

Porte do tocador Stylus (PC/Android) para PS Vita: biblioteca local com capas,
estante de álbuns, deck vinil em âmbar sobre quase-preto, playlists,
recomendações e registro de escuta.

Áudio: MP3 (a família MPEG-1/2 layer I–III, via mpg123).

## Instalar

1. Copie `vitastylus.vpk` para o cartão.
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

Arquivos `.flac`, `.m4a`, `.ogg`, `.opus`, `.wav` e companhia **aparecem na
estante**, marcados como não-tocáveis. Escondê-los faria o app dizer "não
achei nada" para quem tem a coleção inteira em FLAC.

## Controles

| Botão | Estante | Deck (tocando) | Recs | Playlists |
| --- | --- | --- | --- | --- |
| D-pad | navega (repete se segurar) | ◄► troca faixa · ▲▼ seek ±10 s | navega | navega |
| ✕ / ○ | toca o disco | pausa / recomeça | toca a partir da marcada | toca |
| △ | vai ao que está tocando | volta à estante | estante | estante |
| □ | — | seek −10 s | — | guarda o que toca como lista |
| L1 / R1 | recs / playlists | recs / playlists | ↔ | ↔ |
| Select | alterna sorteio | cicla repetição | — | apaga a lista (2 toques) |
| Start | sai | sai | sai | sai |

Repetição: `[select]` no deck cicla **todas → uma → desligada**.

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

- **o núcleo, exercitado de verdade** (`tools/host_test.c`): uma coleção de
  mentira é montada em disco e varrida — ordem das faixas, número tirado do
  nome, faixas soltas na raiz, FLAC marcado, dedup de raízes, `roots.txt`, e
  as duas frases diferentes de "não achei nada";
- **a geometria das telas** (`src/ui_layout.c` é puro de propósito): toda a
  grade, o disco, a coluna de texto e as listas medidos contra a tela, em
  várias resoluções. É o defeito mais repetido deste projeto e o único jeito
  de pegá-lo sem abrir janela;
- a paleta pelo `RGBA8` (ver abaixo), tecla prometida no rodapé e não tratada,
  função órfã, lista de extensão duplicada, caminho montado à mão, heap
  declarado.

Cada uma foi medida com o defeito posto de propósito: seis dos sete sabotados
ficam vermelhos.

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

## A lei do desenho (§5.5)

O vinil existe para tornar ouvir música digital menos chato dando a SENSAÇÃO
analógica. O desenho é fósforo, não foto: disco de luz no quase-preto, âmbar
como única cor viva, o braço é o FACHO (o corpo começa a 38% do caminho, quase
toda a luz na ponta, levantado apaga). **Nada de** madeira, plinto, parafuso,
contrapeso, cabeçote, sala ou poeira de ambiente. O `check.sh` recusa essas
palavras no código do desenho e confere a paleta em números.

## O que ainda não existe

- [ ] Teste em aparelho de verdade (este VPK foi construído e conferido no
      host; o hardware não passou por ele)
- [ ] FLAC/OGG/M4A decode — o scanner já os enumera e os marca
- [ ] Qobuz/streaming (precisa de rede real no Vita para valer)
- [ ] Áudio em segundo plano: **limite de plataforma, não de código.** O Vita
      SUSPENDE o app quando você abre outro. Nenhum homebrew de app comum
      continua tocando por trás; só um plugin de CFW, que é outro projeto. O
      que este VPK faz é voltar exatamente de onde estava, em pausa.
