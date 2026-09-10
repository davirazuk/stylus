# Referências visuais — Sonara e SpotiFLAC

Notas tiradas das telas DE VERDADE dos dois projetos (screenshots baixados e
olhados, não descrições de README). Valem para os dois lados: o `vitastylus`
no aparelho e o deck do Stylus OS no PC.

O que interessa aqui não é copiar aparência — é ver que problema cada padrão
resolve, porque metade deles resolve um problema que estes apps também têm.

---

## Sonara — `kaungset03/sonara`

Tauri + React, local-first, desktop. "Fast. Local-first. Distraction-free."

### 1. Home em SEÇÕES, não em lista

A tela inicial é uma pilha de faixas horizontais:

    Continue Listening   4 cards
    Browse Library       Songs 326 · Artists 82 · Albums 79 · Favorites 43
    Most Played          8 cards          [View All]
    Recently Added       8 cards          [View All]

**O que resolve:** "abri o app, e agora?". Uma estante de 388 discos em
ordem alfabética não responde isso; "continue de onde parou" e "o que você
mais toca" respondem.

**Aplicável aqui:** o `rec.c` já guarda histórico e contagem de escutas, e o
app já monta recomendações. O dado existe e nunca virou tela de entrada.

### 2. Contagens como CARD, não como rodapé

Songs / Artists / Albums / Favorites viram quatro blocos grandes com o número
em corpo enorme. Hoje o vitastylus escreve "1 of 414 records" em cinza de
13 px no rodapé.

### 3. Barra do tocador SEMPRE presente

Embaixo, em todas as telas: capa pequena, título, artista, coração, volume,
tempo decorrido, barra, tempo total, shuffle, anterior, play, próxima,
repetir, fila. Ela é **translúcida** — o conteúdo aparece por baixo.

**O que resolve:** saber o que está tocando sem sair de onde se está. Nos
dois projetos daqui é preciso VIAJAR até o deck para ver isso.

### 4. O fallback de artista/álbum é DIGNO

Sem imagem, o artista vira um círculo azul-acinzentado com as INICIAIS
("KB", "LX", "MT"). Álbum sem capa vira um quadrado com a inicial, ou "CD".
Nunca um buraco, nunca um ícone genérico repetido.

**Aplicável aqui:** é a resposta para "artists also have no images". O
vitastylus já faz algo parecido no disco de placeholder (a letra no rótulo);
falta ele existir numa tela de ARTISTAS, que ainda não existe.

### 5. Cabeçalho de coleção

Título gigante, contagem em cinza, e três botões-pílula: **Play All**
(cheio, acento), **Shuffle** (cheio, acento), **Add Songs** (contorno). Só
depois a tabela, com cabeçalho de coluna (`# · Title · Artist · Album ·
Duration · Actions`).

**O que resolve:** a ação principal fica ANTES da lista, do tamanho de um
alvo de dedo. No vitastylus tocar uma playlist inteira é uma tecla que a
tela não desenha.

### 6. Grade de álbuns sem moldura

7 colunas, capa quadrada sem borda, título em negrito e artista em cinza
embaixo. **A arte É o card.** O que está tocando fica com o título no acento.

---

## SpotiFLAC — `spotbye/SpotiFLAC`

Desktop (Tauri-ish), painel escuro sobre a janela do sistema.

> **O nome engana.** O assunto do SpotiFLAC não é o Spotify: é LOSSLESS.
> O Spotify aparece só como uma das formas de dizer QUAL disco se quer. Eu
> li o nome literalmente na primeira passada e construí uma ferramenta de
> "cole um link do Spotify" — errado; o que interessa é procurar por nome e
> receber FLAC. Corrigido: virou o `stylus-flac`.

### 1. Uma tarefa, uma tela, um campo

Logo centralizado, uma frase dizendo o que o programa faz, e então:

    [ https://open.spotify.com/track/...        ] [colar] [ Fetch ]

Nada mais. O botão de ação é o único elemento em cor cheia da tela — e a cor
é âmbar/ouro, a mesma família do acento do Stylus.

**O que resolve:** a tela inteira é a pergunta que o programa faz. Não há o
que aprender antes de usar.

### 2. Trilho de ícones à esquerda, sem rótulo

Uma coluna estreita: início, histórico, ajustes, terminal, extensões, ajuda.
Ícone só, sem texto. O item ativo ganha um quadrado arredondado de fundo.

**Comparar:** aqui as abas são uma fila horizontal de PALAVRAS no topo, o que
custa altura. Num aparelho de 544 px de altura isso importa.

### 3. Histórico como pílulas + cards com CRACHÁ DE TIPO

    Recent Searches:  ( taylor swift )  ( golden )

    Recent Fetches:   card com capa, título, "10 tracks", e um crachá
                      colorido: Track (azul) · Album (verde) ·
                      Playlist (roxo) · Artist (laranja)

**O que resolve:** numa lista mista, o tipo do item se lê pela COR antes de
se ler a palavra. O vitastylus mistura álbum, faixa e playlist em várias
telas e distingue os três por... nada.

---

## O que eu levaria para cada lado

**vitastylus (aparelho) — o que JÁ foi feito:**
- **aba HOME** (`VIEW_HOME`, a primeira do anel): continuar · a coleção em
  números · mais tocados · nunca tocados. As duas últimas saem do `rec.c`,
  que contava escutas há meses sem que ninguém visse o número. Seção vazia
  COLAPSA — um travessão sozinho não pode reservar 130 px.
- **aba ARTISTS** (`VIEW_ARTISTAS`): grade de círculos, capa quando existe e
  INICIAIS quando não; escolher um filtra a estante por ele (reusa o filtro
  que já casava por artista, em vez de inventar uma segunda tela de discos).

- **a pílula `GET FLAC`** na linha do sinal do deck: acha a MESMA música no
  Qobuz e toca a versão lossless no lugar do arquivo do cartão. Ver abaixo.

- **buscas recentes em pílulas** na loja (do SpotiFLAC): seis termos,
  guardados em `buscas.txt`, tocáveis. Num teclado de Vita repetir "polaroid
  yung lixo" era redigitar a frase inteira; agora é um toque. A tela da loja
  vazia era duas linhas e quatrocentos pixels de preto.
- **pílulas de ação** antes das listas — e a PRINCIPAL é cheia, não contorno:
  as duas iguais liam como dois botões desabilitados.
- **JUST ADDED na home**, saindo da data da PASTA (`Album.mtime`, que a
  varredura já lia para conferir o índice e não guardava). É a pergunta de
  quem baixa música, e a estante alfabética não a responde.
- **o tamanho das capas da home sai do espaço que sobra**, e não de um 86
  fixo: com três faixas ele estourava a tela em 130 px, e o número de faixas
  com conteúdo muda (uma seção vazia colapsa).
- **a grade de ARTISTS virou 6×3** — eram 85 px de faixa morta entre as duas
  fileiras, e 109 artistas a doze por página são nove viradas de página.

  ainda por fazer:
- faixa de tocando-agora nas telas de lista (não só no deck)

  **o crachá de tipo colorido saiu da lista.** Ele resolve "numa lista
  MISTURADA, o tipo se lê pela cor antes de se ler a palavra" — e este app
  não tem lista misturada: a busca do Qobuz devolve só álbum, as RECS só
  faixa, as LISTS só playlist. Um crachá aqui marcaria a única coisa que
  cada tela já contém, que é ruído com aparência de informação. Se um dia
  uma tela juntar os três, ele volta.

**Stylus OS (PC):**
- a mesma arquitetura de informação no lançador (`stylus-deck` já desenha a
  tela cheia; falta a home em seções)
- o trilho de ícones à esquerda em vez de abas no topo
- a tela de "uma tarefa, um campo" do SpotiFLAC serve inteira para o
  buscador/baixador do Qobuz

---

## O que virou código: `stylus-flac`

A metade útil do SpotiFLAC — **procurar um disco pelo nome e receber
lossless** — está no `airootfs/usr/local/bin/stylus-flac` do Stylus OS:

    stylus-flac "radiohead in rainbows"      acha e baixa em FLAC
    stylus-flac --listar "slowdive"          só mostra
    stylus-flac -n 2 "in rainbows"           baixa o segundo resultado
    stylus-flac --faixa "creep radiohead"    faixa em vez de disco
    stylus-flac --formato hires "loveless"   24/96

A FONTE é o Qobuz **do dono da máquina** — as credenciais saem do
`~/.config/qobuz-dl/config.ini`, a mesma assinatura paga que o tocador do
Vita já usa para buscar e baixar. É o mesmo caminho do `src/qobuz.c`, em
Python e no PC.

Link do Spotify é aceito, mas não é o assunto: dele se lê só o METADADO
(título e artista, da página pública de embed) para virar termo de busca.
Nenhum áudio vem de lá — e o dono desta máquina não gosta do Spotify.

A TELA do SpotiFLAC, essa sim, vale copiar inteira — está nas notas acima.

### As FONTES, que é o que ele faz de melhor

O pedido foi direto: *"na parte do spotiflac eu gosto muito de como ele
instala qobuz, soundcloud, amazon music e mais, ele tem até youtube music"*.
É o acerto dele — uma pergunta ("quero este disco"), várias portas.

    stylus-flac --fontes                      o que cada uma dá
    stylus-flac "in rainbows"                 qobuz, o padrão
    stylus-flac -f arquivo "radiohead 1993"   shows do archive.org, em FLAC
    stylus-flac -f soundcloud "burial mix"    o que só existe lá
    stylus-flac -f youtube "..."              o catálogo mais largo
    stylus-flac --todas "souvlaki"            as quatro de uma vez

| fonte | o que é | lossless |
| --- | --- | --- |
| `qobuz` | a assinatura PAGA do dono da máquina | **sim**, até 24/192 |
| `arquivo` | archive.org — shows liberados pelas bandas | **sim**, FLAC |
| `soundcloud` | remix, set, inédito | não (MP3/Opus) |
| `youtube` | o catálogo mais largo que existe | não (Opus ~160) |

**A coluna de qualidade é a peça, não o enfeite.** Uma ferramenta chamada
"flac" que devolve um Opus de 160 kbps reempacotado em `.flac` está mentindo
— o arquivo ganha a extensão e a música já perdeu o que perdeu. Aqui toda
linha diz o que é, um `♦` marca o que é lossless de verdade, a lista mistura
ordenada com o lossless em cima, e escolher um com perda imprime um aviso
ANTES de baixar. Nada é convertido para `.flac` ao ser guardado.

**O `arquivo` foi a descoberta desta leva.** O SpotiFLAC não o tem, e ele é
o que mais combina com ESTE acervo: a coleção do dono é feita de gravações
ao vivo com nome de data (`1993-02-11 - Radiohead - Signal Radio Session`), e
o archive.org tem exatamente isso, em FLAC, de graça e sem conta. A primeira
busca de teste — "radiohead 1993" — devolveu como primeiro resultado o MESMO
show que já está no cartão do Vita.

Uma armadilha vale anotar: a consulta óbvia é `collection:(etree)`, o Live
Music Archive. Ela devolve ZERO para Radiohead — o etree só aceita banda que
autoriza troca de gravação — e zero lê como "o archive não tem", quando ele
tem. O filtro certo é `format:(Flac)`: acha aquilo e ainda garante que só
entram itens com áudio lossless de verdade.

**Amazon Music não entrou, de propósito.** O áudio de lá sai com DRM, e
tirá-lo quer dizer quebrar essa proteção — não é uma limitação técnica que
falte resolver. Para lossless pago, o `qobuz` já faz o serviço, legalmente,
com a conta que o dono já assina. O `--fontes` diz isso na cara, em vez de
a fonte simplesmente não existir sem explicação.

---

## A pílula `GET FLAC` — o SpotiFLAC dentro do tocador

    "um botão que, em vez de tocar o mp3 local, procura e toca
     a versão em flac do qobuz"

Ela mora no FIM DA LINHA DO SINAL do deck, e o lugar é o argumento: é ali
que a pessoa já está lendo `MP3 · 44100 Hz / 16 bits`. Em qualquer outro
canto seria mais um atalho a decorar; ali é resposta à frase que ela acabou
de ler. Só aparece quando há o que trocar — faixa do cartão, conta do Qobuz
configurada — e o rótulo diz o GANHO: `GET FLAC` num arquivo com perda,
`GET HI-RES` num que já é lossless.

**A parte difícil não é a rede, é decidir se é a mesma música.** Procurar
"Radiohead Creep" traz, em ordem: a de estúdio, a acústica, três ao vivo,
duas remasterizações e um cover. Título e artista batem em TODAS. O que
separa as gravações é a DURAÇÃO — e ela vem de graça na resposta. Daí o
peso do casamento: título parecido é obrigatório (30%), artista conta
(25%), e a duração vale mais que os dois juntos (45%), porque é ela que
responde a pergunta que o título não responde. Abaixo de 60 de 100 o app
diz que NÃO achou, e conta o que chegou perto — trocar a gravação que a
pessoa escolheu por outra, em silêncio, é a forma cara de errar aqui.
