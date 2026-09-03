# vitastylus — tocador de música para PS Vita

Porte do tocador Stylus (PC/Android) para PS Vita: biblioteca local com
capas, estante de álbuns, deck vinil em âmbar sobre quase-preto, playlists,
recomendações e registro de escuta. Parte do desafio "homebrew para Vita".

Toca música local MP3 de `ux0:music/`.

## Build

Requisitos (nesta máquina):
- VitaSDK em `~/vitasdk` (`export VITASDK=$HOME/vitasdk; export PATH=$VITASDK/bin:$PATH`)
- vdpm com: libvita2d r188, vitaShaRK 1.5, libpng, libjpeg-turbo, mpg123, sdl2

```sh
cd ~/stylus/vita/player
./build.sh
```

Saída: `build/vitastylus.vpk`.

## Instalar no Vita

1. Copie `build/vitastylus.vpk` para o cartão SD2VITA (ux0:).
2. Instale via VitaShell (o arquivo .vpk).
3. Música em `ux0:music/<Artista>/<Álbum>/*.mp3` (+ `.m4a`/`.wav`/`.ogg`/`.flac`
   que o scanner enumera; o decodificador é MP3).
4. Dados do app em `ux0:data/vitastylus/`:
   - `playlists/*.m3u` — as playlists (M3U8)
   - `history.txt` — contagem por faixa (base das recomendações)
   - `stylus-scrobbles.tsv` — registro de escuta, MESMO formato do Android
     do Stylus: `timestamp<TAB>artista<TAB>álbum<TAB>pasta`

## Controles

| Botão | Estante | Deck (tocando) | Recs | Playlists |
| --- | --- | --- | --- | --- |
| D-pad | navega grade | ◄► troca faixa · ▲▼ seek ±10s | navega | navega |
| Cross/O | toca álbum | pausa/recomeça | toca recs | toca playlist |
| Square | — | seek −10s (legado) | — | cria playlist do atual |
| Triângulo | — | estante | estante | estante |
| L1 / R1 | recs / playlists | recs / playlists | — | — |
| Select | alterna sorteio | cicla repetição | — | — |
| R2 | — | — | — | apaga playlist (2 toques) |

Repetição: `[select]` no deck alterna **todas → uma → desligada**. O estado
(shuffle/rep) aparece no rodapé do deck. A estante marca o disco em reprodução
com um quadradinho âmbar no canto do card; recs e playlists mostram a capa/
disco da linha.

## Continuar onde parou

O app grava (a cada ~0,5s) faixa, posição, repetição e sorteio em
`ux0:data/vitastylus/last_session`. Ao abrir de novo, volta para essa faixa
**em pausa** — `[O]` recomeça. Isso sobrevive a suspensão/queda sem saída
limpa.

## Recomendações

O histórico conta faixas COMPLETADAS (tocadas até o fim). A tela de
recomendações (`[L1]`) monta uma lista: discos nunca ouvidos primeiro,
ponderados pela afinidade dos artistas que a pessoa mais ouviu. Tocar com
`[O]`/`[dir]`.

## Scrobbling (registro de escuta)

O player grava uma linha por disco posto em `stylus-scrobbles.tsv` (formato
idêntico ao do Android). Para entrar na memória da coleção no PC, traga o
arquivo e rode `stylus phone scrobbles` — o mesmo canal que já junta o que
tocou no celular (resolução por artista/álbum quando a pasta não casa).

## Background audio (o que é possível no Vita)

**Limite de plataforma, não de código:** o Vita SUSPENDE o aplicativo quando
você abre outro (um jogo) — o áudio para junto. Nenhum homebrew de app comum
consegue continuar tocando por trás. As únicas saídas reais são plugin de CFW
(VitaShell/reB00t) que possui o áudio à parte do app em primeiro plano; isso
é desenvolvimento de plugin de sistema, fora do escopo deste VPK. O que o
VPK faz é manter o estado na memória: o Vita suspende (não mata), então voltar
de um jogo retoma exatamente de onde estava, pausado — é só `[O]` para
recomeçar. Não há como prometer áudio em jogo sem um plugin.

## Qobuz (arquitetura, não implementado)

O cliente de streaming pede: módulos NET/HTTP/SSL (já pré-carregados em
`load_modules`), a assinatura MD5 do Qobuz (a mesma lógica de
`qobuz_stream.py` no PC, que usa `get_album_meta` + `userLibrary`/favoritos e
sai da re-geração de assinatura sozinha), OAuth do usuário e um stream/URL
com expiração (~1h). Precisa de rede real no Vita para validar — marco de
sessão futura. Hoje o app é local, sem fingir o streaming.

## Estrutura

- `src/main.c` — loop principal, vida2d, carga de módulos, sessão (playlists/recs/scrobble)
- `src/library.c/.h` — varredura recursiva de `ux0:music/`, agrupamento, ordenação, capas
- `src/tags.c/.h` — leitura de ID3v2 (título/artista/álbum/faixa/duração/capa)
- `src/player.c/.h` — decodificação (mpg123)→anel→SDL2; sessão (slots), shuffle, repetição, seek
- `src/playlist.c/.h` — M3U8 (carregar/salvar/criar com nome único)
- `src/rec.c/.h` — histórico por faixa e construção da lista recomendada
- `src/scrobble.c/.h` — registro de escuta em TSV compatível com o PC
- `src/resume.c/.h` — ponto de continuação (faixa+posição+rep+sorteio)
- `src/ui.c/.h` — estante, deck vinil (disco âmbar, sulcos, agulha, halo), recs, playlists
- `CMakeLists.txt` / `build.sh` — pipeline VPK (vita.cmake)

## Teste fora do Vita (host)

O núcleo (biblioteca + tags + playlists + recs + scrobble) é testável no PC,
sem VitaSDK, contra o `libmpg123` do sistema:

```sh
cd ~/stylus/vita/player/src
gcc -O1 -o /tmp/opencode/vita_core_test /tmp/opencode/vita_core_test.c \
  library.c tags.c rec.c playlist.c scrobble.c \
  -Isrc $(pkg-config --cflags --libs libmpg123)
/tmp/opencode/vita_core_test "/home/davirazuk/staging-vita/vita-mp3/"
```

A lógica de shuffle/repetição (`player.c`) é validada por uma réplica em
host (`/tmp/opencode/vita_shuffle_test.c`): permutação correta, wrap de
repetição, repeat-um fica parado, repeat-off para no fim, shuffle começa na
faixa pedida.

## Estado

- [x] VPK compila sem warnings (~1.18 MB), jogada completa no host
- [x] Biblioteca: agrupamento/ordenação/capas (405 álbuns, 339 com capa)
- [x] Sessão: álbum, playlists, recomendações — com shuffle/repetição
- [x] Playlists M3U8 (criar/salvar/carregar/apagar), criação com nome único
- [x] Recomendações por histórico de completação (com capas)
- [x] Registro de escuta (TSV compatível com `stylus phone scrobbles`)
- [x] Continuar a sessão onde parou (faixa+posição em pausa)
- [ ] Teste de hardware no Vita (cartão no aparelho; sem via de cópia confirmada)
- [ ] FLAC/OGG decode (o scanner já enumera; o cartão atual é MP3)
- [ ] Qobuz/streaming e scrobbling online (precisa de rede real; ver acima)
- [ ] Background audio em jogo (requer plugin de CFW; ver acima)
