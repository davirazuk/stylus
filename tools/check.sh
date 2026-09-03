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
          tools/host_test.c tools/tags_stub.c "$SRC"/library.c "$SRC"/fsutil.c "$SRC"/ui_layout.c 2>&1)
    if [ $? -ne 0 ]; then
        fail "o teste de host não compila" "$out"
    else
        if /tmp/vitastylus_host_test; then pass "as conferências do núcleo passam"
        else fail "o teste de host reprovou (a saída está acima)"; fi
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
# assim que album_load_cover existia e nenhuma capa era carregada.
orphans=""
for fn in album_load_cover album_load_meta library_status library_roots_from \
          mkdir_p path_join ui_draw_scanning player_last_error player_track_duration \
          ui_rec_idx drain_done; do
    n=$(grep -how "$fn" "$SRC"/*.c "$SRC"/*.h tools/*.c 2>/dev/null | wc -l)
    # 1 = só a definição; 2 = definição + protótipo. Chamada de verdade é >2.
    [ "$n" -le 2 ] && orphans="$orphans $fn"
done
if [ -n "$orphans" ]; then
    fail "escrita e nunca chamada:$orphans"
else
    pass "toda peça do núcleo tem alguém que a chama"
fi

printf '\n\033[1muma lista, um dono\033[0m\n'
# Seis listas de extensão de áudio que discordavam entre si custaram caro no
# desktop. Aqui a resposta mora no library.c e em lugar nenhum mais.
n=$(grep -l '"\.mp3"' "$SRC"/*.c | wc -l)
if [ "$n" -le 1 ]; then
    pass "a lista de extensões de áudio existe em UM arquivo"
else
    fail "há mais de uma lista de extensão de áudio" "$(grep -l '"\.mp3"' "$SRC"/*.c)"
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
