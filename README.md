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
- **O disco fica na tela enquanto toca.** O *deck* desenha o LP com os
  sulcos tirados da intensidade medida do álbum, o braço no raio de agora e
  a capa girando no meio. Raio é tempo: bater o olho diz quanto falta do
  lado, sem número nenhum.
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
| `stylus deck [DISCO]` | põe um disco e abre o deck: a cerimônia inteira |
| `stylus record` | sorteia um da estante, puxando para os esquecidos |
| `stylus shelf` | a estante em grade de capas |
| `stylus ui` | a tela cheia (é o que o modo música abre) |

### A coleção
| | |
|---|---|
| `stylus library [PASTA]` | onde ela fica (descoberto sozinho na primeira vez) |
| `stylus diary` | o que você pôs, quando, quantas vezes |
| `stylus check` | o que está quebrado lá dentro |
| `stylus gaps ARTISTA` | que discos desse artista faltam |
| `stylus lyrics` | procura e grava `.lrc` sincronizado |
| `stylus covers` | `cover.jpg` onde falta |
| `stylus rip` | rasga o CD da gaveta, conferido no AccurateRip |
| `stylus get URL` | baixa e arquiva na estrutura certa |

### As máquinas
| | |
|---|---|
| `stylus phone` | o celular: estado, sincronizar, playlists, scrobbles |
| `stylus audio` | o caminho do sinal, medido |
| `stylus app NOME` | Clone Hero, qobuz-dl, Proton-GE, o que não vem em pacote |
| `stylus update` | traz o STYLUS novo do GitHub |
| `stylus mode` | troca entre música e área de trabalho |
| `stylus atalhos` | a lista de atalhos de teclado |
| `stylus instalar` | instala no computador (a partir do pendrive) |

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

---

## De onde vem

O maquinário de hardware (instalador, driver de vídeo, mouse, controle,
escala de tela) veio do [IFOS](https://github.com/davirazuk/ifos), a outra
distribuição do mesmo autor, e foi rebatizado. É código testado contra
máquinas quebradas de formas que esta não está; reescrever produziria uma
versão pior.

Tudo que dá identidade ao STYLUS — o deck, a estante, a memória da coleção, o
caminho de áudio, a interface de tela cheia, os dois modos, o celular — é
deste projeto.
