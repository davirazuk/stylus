#!/bin/sh
# As conferências do vitastylus. Rode ANTES de empurrar.
#
# Roda em qualquer máquina com gcc: nada aqui precisa de VitaSDK nem de Vita.
# O teste de host exercita a varredura (que é onde moravam os defeitos que
# deixavam a estante vazia); o resto são conferências de LEITURA sobre coisas
# que só existem na RELAÇÃO entre dois arquivos — que é onde ler um por vez
# não pega nada.

cd "$(dirname "$0")/.." || exit 1
SRC=src
fails=0
pass()  { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail()  { printf '  \033[31m✗\033[0m %s\n' "$1"; [ -n "$2" ] && printf '      %s\n' "$2"; fails=$((fails+1)); }
skip()  { printf '  \033[33m—\033[0m %s\n' "$1"; }

printf '\033[1msintaxe\033[0m\n'
for f in tools/*.sh; do
    if sh -n "$f" 2>/dev/null; then pass "sh -n $f"; else fail "sh -n $f"; fi
done

printf '\n\033[1mnúcleo (teste de host)\033[0m\n'
if ! command -v gcc >/dev/null 2>&1; then
    skip "PULA: sem gcc nesta máquina"
else
    out=$(gcc -std=gnu11 -Wall -Wextra -Werror -I"$SRC" -o /tmp/vitastylus_host_test \
          tools/host_test.c tools/decoder_stub.c "$SRC"/library.c "$SRC"/fsutil.c \
          "$SRC"/ui_layout.c "$SRC"/sides.c "$SRC"/lyrics.c -lm 2>&1)
    if [ $? -ne 0 ]; then
        fail "o teste de host não compila" "$out"
    else
        if /tmp/vitastylus_host_test; then pass "as conferências do núcleo passam"
        else fail "o teste de host reprovou (a saída está acima)"; fi
    fi
fi

printf '\n\033[1mdecodificadores (contra áudio de verdade)\033[0m\n'
# Este é o único teste que precisa de coisa de fora: as bibliotecas de áudio
# e os codificadores que geram as fixtures. Onde não houver, PULA — uma
# conferência que reprova por falta de dependência ensina a ignorar a
# conferência inteira.
DEC_PKGS="libmpg123 flac vorbisfile opusfile"
if ! command -v gcc >/dev/null 2>&1 || ! command -v pkg-config >/dev/null 2>&1; then
    skip "PULA: sem gcc/pkg-config"
elif ! pkg-config --exists $DEC_PKGS 2>/dev/null; then
    skip "PULA: faltam as bibliotecas ($DEC_PKGS)"
elif ! command -v flac >/dev/null 2>&1 \
   || { ! command -v ffmpeg >/dev/null 2>&1 \
        && { ! command -v oggenc >/dev/null 2>&1 \
             || ! command -v opusenc >/dev/null 2>&1 \
             || ! command -v lame >/dev/null 2>&1; }; }; then
    # o ffmpeg cobre ogg/opus/mp3 sozinho; os dedicados são só o caminho
    # preferido. Exigir os três fazia esta máquina PULAR o teste inteiro por
    # falta do vorbis-tools — e um teste que pula em silêncio é o mesmo que
    # não existir.
    skip "PULA: faltam os codificadores (flac, e ffmpeg ou oggenc+opusenc+lame)"
else
    FX=/tmp/vitastylus_fixtures
    # Regerar quando FALTA QUALQUER UMA. Antes olhava só o tone.flac: uma
    # fixture nova (o mp3 de 48 kHz do teste do teto) nunca era criada porque
    # o flac já estava lá, e o teto passava sem ser exercitado.
    for _fx in tone.flac tone.ogg tone.opus tone.mp3 tone48k.mp3 tone24.flac; do
        if [ ! -f "$FX/$_fx" ]; then
            python3 tools/make_fixtures.py "$FX" >/dev/null 2>&1 || true
            break
        fi
    done
    if [ ! -f "$FX/tone.flac" ]; then
        fail "não consegui gerar as fixtures de áudio"
    else
        out=$(gcc -std=gnu11 -Wall -Wextra -Werror -I"$SRC" -o /tmp/vitastylus_dectest \
              tools/decoder_test.c "$SRC"/decoder.c \
              $(pkg-config --cflags $DEC_PKGS) $(pkg-config --libs $DEC_PKGS) -lm 2>&1) || true
        if [ ! -x /tmp/vitastylus_dectest ]; then
            fail "o teste do decodificador não compila" "$out"
        elif /tmp/vitastylus_dectest "$FX"; then
            pass "FLAC sai idêntico ao original, e os cinco formatos decodificam"
        else
            fail "o teste do decodificador reprovou (a saída está acima)"
        fi
    fi
fi

printf '\n\033[1mos lados: as duas metades cortam igual\033[0m\n'
# Não compara marcador nem trecho de código — compara o CORTE, repartindo a
# MESMA grade de discos pelas duas regras. As peças podem estar todas
# presentes e o resultado sair diferente, que foi o que aconteceu com o
# celular quando o teto físico entrou só de um lado. E o lado de lá é o
# vinyl.py DE VERDADE, não uma cópia dele: uma cópia derivaria.
if ! command -v gcc >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
    skip "PULA: sem gcc/python3"
else
    gcc -std=gnu11 -Wall -Wextra -Werror -I"$SRC" -o /tmp/vitastylus_sides_dump \
        tools/sides_dump.c "$SRC"/sides.c -lm 2>/dev/null
    if [ ! -x /tmp/vitastylus_sides_dump ]; then
        fail "o despejo dos lados não compila"
    else
        out=$(python3 tools/compara_lados.py /tmp/vitastylus_sides_dump 2>&1)
        rc=$?
        if [ $rc -eq 77 ]; then
            skip "$(echo "$out" | head -1)"
        elif [ $rc -eq 0 ]; then
            pass "$(echo "$out" | tail -1)"
        else
            fail "o corte dos lados DIVERGE do desktop" "$out"
        fi
    fi
fi

printf '\n\033[1ma lei do desenho (§5.5)\033[0m\n'
# O vita2d empacota ABGR. Cor escrita à mão em hexadecimal sai TROCADA e
# ninguém vê lendo: "0xFFFFAA28" lê como âmbar e desenha azul-celeste.
bad=$(grep -nE '#define +COL_[A-Z_]+ +0x' "$SRC"/ui.c)
if [ -n "$bad" ]; then
    fail "cor da paleta escrita em hexadecimal à mão (use RGBA8)" "$bad"
else
    pass "a paleta passa pelo RGBA8, que é quem sabe a ordem dos bytes"
fi
# O âmbar é a única cor viva: vermelho acima do azul no que é luz.
if grep -q 'COL_AMBER *RGBA8(255, *170, *40' "$SRC"/ui.c; then
    pass "o âmbar é âmbar (255,170,40)"
else
    fail "o COL_AMBER mudou de cor"
fi
# CÓDIGO, não comentário. A versão anterior desta conferência reprovava o
# próprio comentário que a explica ("nada de madeira, plinto, parafuso") — já
# aconteceu duas vezes no desktop, e uma conferência que grita sobre o que
# está certo é uma que se aprende a ignorar. O -fpreprocessed tira os
# comentários sem expandir include nenhum.
movel=0
if command -v gcc >/dev/null 2>&1; then
    gcc -fpreprocessed -dD -E -P "$SRC"/ui.c > /tmp/vitastylus_ui_nocomment.c 2>/dev/null
    for palavra in plinth plinto prateleira parafuso madeira contrapeso \
                   cabecote headshell cartridge counterweight nebula poeira; do
        if grep -qi "$palavra" /tmp/vitastylus_ui_nocomment.c; then
            fail "móvel de toca-discos no CÓDIGO do desenho: $palavra"
            movel=1
        fi
    done
    [ "$movel" -eq 0 ] && pass "nada de móvel, plinto ou parafuso no desenho"
else
    skip "PULA: sem gcc para separar código de comentário"
fi

printf '\n\033[1mos caracteres que a fonte desenha\033[0m\n'
# Um caractere que a fonte não tem não some: vira quadradinho na tela, e no
# editor aparece perfeito. Já aconteceu com uma seta na linha do sinal.
if command -v python3 >/dev/null 2>&1; then
    out=$(python3 tools/glifos.py "$SRC"/ui.c 2>&1) || true
    if [ -z "$out" ]; then
        pass "a UI só usa caracteres do conjunto seguro"
    else
        fail "a UI usa caractere que a fonte pode não ter" "$out"
    fi
else
    skip "PULA: sem python3"
fi

printf '\n\033[1mo que a tela promete\033[0m\n'
# Uma tecla escrita no rodapé e não tratada pelo input é a família do
# stylus-welcome: promessa sem destino. E o Vita NÃO TEM L2/R2.
if grep -q 'SCE_CTRL_R2\|SCE_CTRL_L2' "$SRC"/ui.c; then
    fail "o Vita não tem L2/R2: essa tecla não existe em aparelho nenhum"
else
    pass "nenhuma tecla que o aparelho não tem"
fi
for k in 'quad' 'tri' 'sel'; do
    if grep -q "\[$k\]" "$SRC"/ui.c; then
        case $k in
          quad) sym=SCE_CTRL_SQUARE ;;
          tri)  sym=SCE_CTRL_TRIANGLE ;;
          sel)  sym=SCE_CTRL_SELECT ;;
        esac
        if grep -q "$sym" "$SRC"/ui.c; then pass "[$k] é prometida e tratada"
        else fail "[$k] aparece no rodapé e o input nunca a lê"; fi
    fi
done

printf '\n\033[1mfunção órfã\033[0m\n'
# Um helper que ninguém chama costuma ser um recurso INTEIRO faltando: foi
# assim que album_load_cover existia e nenhuma capa era carregada, e assim que
# album_free_cover existia e os bytes crus de toda capa vista ficavam na
# memória para sempre.
#
# Isto já foi uma lista de nomes escrita à mão aqui. Ela só pega o que alguém
# lembrou de escrever nela — e NENHUM dos dois defeitos acima estava na lista;
# os dois foram achados a olho. Agora a lista sai dos próprios headers.
if command -v python3 >/dev/null 2>&1; then
    out=$(python3 tools/orfas.py "$SRC" tools tests 2>&1) || true
    if [ -z "$out" ]; then
        pass "toda função declarada nos headers tem quem a chame"
    else
        fail "declarada e nunca chamada" "$out"
    fi
else
    skip "PULA: sem python3"
fi

printf '\n\033[1muma lista, um dono\033[0m\n'
# Seis listas de extensão de áudio que discordavam entre si custaram caro no
# desktop. Aqui a resposta mora no library.c e em lugar nenhum mais.
# Duas perguntas, dois donos, e nenhuma escrita duas vezes: "isto é música?"
# é do library.c (a estante mostra o que não toca, de propósito) e "eu sei
# tocar isto?" é do decoder.c, que é quem tem os decodificadores.
n=$(grep -l '"\.mp3"' "$SRC"/*.c | wc -l)
if [ "$n" -le 2 ]; then
    pass "cada pergunta sobre formato tem um dono só"
else
    fail "lista de extensão espalhada" "$(grep -l '"\.mp3"' "$SRC"/*.c)"
fi
if grep -q 'decodable_ext.*dec_kind_of' "$SRC"/library.c; then
    pass "a estante pergunta ao decoder o que ele sabe tocar"
else
    fail "a estante tem a PRÓPRIA ideia do que é tocável (vai divergir)"
fi
# E a pasta dos dados também: escrita em dois lugares, um deles deriva.
n=$(grep -ho 'ux0:data/vitastylus' "$SRC"/*.c | wc -l)
if [ "$n" -le 2 ]; then
    pass "o caminho dos dados é escrito num lugar só"
else
    fail "ux0:data/vitastylus escrito em $n lugares"
fi

printf '\n\033[1mcaminho do Vita\033[0m\n'
# sceIoGetstat recusa "//": montar caminho com printf é como isso volta.
bad=$(grep -n 'snprintf([^,]*, *[^,]*, *"%s/%s"' "$SRC"/library.c)
if [ -n "$bad" ]; then
    fail "caminho montado à mão no scanner (use path_join)" "$bad"
else
    pass "o scanner monta caminho pelo path_join"
fi

printf '\n\033[1mo aparelho\033[0m\n'
# O Vita SUSPENDE sozinho depois de alguns minutos sem toque, e suspenso o
# áudio para: um álbum inteiro nunca chegava ao fim se ninguém encostasse.
if grep -q 'sceKernelPowerTick' "$SRC"/main.c; then
    pass "o timer de suspensão é cancelado enquanto toca"
else
    fail "sem sceKernelPowerTick: o Vita suspende no meio do disco"
fi
# ...mas a TELA pode apagar: é um tocador de música, e o OLED é a bateria.
if grep -q 'DISABLE_OLED' "$SRC"/main.c; then
    fail "não trave a tela acesa: é um tocador, o OLED come a bateria"
else
    pass "a tela continua livre para apagar"
fi
# O painel de toque é 1920x1088, o dobro da tela.
if grep -q 'report\[0\].x / 2' "$SRC"/ui.c; then
    pass "o toque é convertido da resolução do painel para a da tela"
else
    fail "o toque usa coordenadas cruas (todo toque cai no canto)"
fi

printf '\n\033[1ma cerimônia (§5.5)\033[0m\n'
# Abrir o app com música já tocando NÃO encena a cerimônia: o disco não foi
# posto agora, foi encontrado no meio. É a diferença entre um ritual e uma
# animação de abertura.
if grep -q 'ui_skip_ritual' "$SRC"/main.c && \
   grep -A3 'try_resume(&lib, player)' "$SRC"/main.c | grep -q 'ui_skip_ritual'; then
    pass "retomar a sessão NÃO encena a descida da agulha"
else
    fail "o resume encena a cerimônia (mentira sobre o que aconteceu)"
fi
if grep -q 'ui_begin_ritual' "$SRC"/main.c; then
    pass "pôr um disco encena a cerimônia"
else
    fail "nada encena a cerimônia — ela existe e nunca roda"
fi

printf '\n\033[1mmemória\033[0m\n'
if grep -q '_newlib_heap_size_user' "$SRC"/main.c; then
    pass "o heap do app é declarado (o padrão não cabe uma coleção grande)"
else
    fail "sem _newlib_heap_size_user: a varredura para no meio, em silêncio"
fi

printf '\n'
if [ "$fails" -eq 0 ]; then
    printf '\033[32mtudo verde\033[0m\n'
else
    printf '\033[31m%d falha(s)\033[0m\n' "$fails"
fi
exit $([ "$fails" -eq 0 ] && echo 0 || echo 1)
