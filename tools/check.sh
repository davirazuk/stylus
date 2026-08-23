#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  tools/check.sh — tudo que dá para conferir sem construir a ISO
# ═══════════════════════════════════════════════════════════════════════════
#  Construir a ISO leva meia hora. Praticamente todo defeito que já apareceu
#  neste tipo de repositório — nome de pacote errado, link simbólico apontando
#  para um arquivo renomeado, script com erro de sintaxe, config do i3 que o
#  i3 recusa — dá para pegar em segundos. Rode isto antes de construir e antes
#  de empurrar.
#
#      tools/check.sh            tudo
#      tools/check.sh --fast     pula a conferência de pacotes (que usa rede)
# ═══════════════════════════════════════════════════════════════════════════
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

g=$'\033[1;32m'; r=$'\033[1;31m'; y=$'\033[1;33m'; d=$'\033[2m'; z=$'\033[0m'
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  %s✓%s %s\n' "$g" "$z" "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  %s✗%s %s\n' "$r" "$z" "$1"; }
sec()  { printf '\n%s%s%s\n' "$d" "$1" "$z"; }

FAST=0; [[ ${1:-} == --fast ]] && FAST=1

sec "sintaxe de shell"
while IFS= read -r -d '' f; do
    head -c 200 "$f" | grep -qE '^#!.*(bash|sh)\b' || continue
    if bash -n "$f" 2>/dev/null; then ok "${f#./}"; else bad "${f#./} não compila"; fi
done < <(find airootfs tools -type f \( -name '*.sh' -o -perm -u+x \) -print0)

sec "shellcheck"
while IFS= read -r -d '' f; do
    head -c 200 "$f" | grep -qE '^#!.*(bash|sh)\b' || continue
    out=$(shellcheck -S warning "$f" 2>&1) && ok "${f#./}" || {
        bad "${f#./}"; echo "$out" | head -6 | sed 's/^/      /'; }
done < <(find airootfs/usr/local/bin airootfs/usr/share/stylus tools -type f -print0 2>/dev/null)

sec "sintaxe de python"
while IFS= read -r -d '' f; do
    if python3 -c "import ast,io,sys;ast.parse(io.open(sys.argv[1],encoding='utf-8').read())" "$f" 2>/dev/null
    then ok "${f#./}"; else bad "${f#./} não compila"; fi
done < <(find airootfs -name '*.py' -print0)
for f in airootfs/usr/local/bin/stylus-audio airootfs/usr/local/bin/stylus-phone; do
    [[ -f $f ]] || continue
    python3 -c "import ast,io,sys;ast.parse(io.open(sys.argv[1],encoding='utf-8').read())" "$f" \
        && ok "${f#./}" || bad "${f#./} não compila"
done

sec "fish"
if command -v fish >/dev/null; then
    while IFS= read -r -d '' f; do
        fish -n "$f" 2>/dev/null && ok "${f#./}" || bad "${f#./}"
    done < <(find airootfs -name '*.fish' -print0)
else
    printf '  %s—%s fish não instalado aqui\n' "$y" "$z"
fi

sec "i3"
if command -v i3 >/dev/null; then
    for c in airootfs/etc/skel/.config/i3/config airootfs/usr/share/stylus/i3-music.config; do
        [[ -f $c ]] || continue
        i3 -C -c "$c" >/dev/null 2>&1 && ok "${c#./}" || { bad "${c#./}"; i3 -C -c "$c" 2>&1 | head -4 | sed 's/^/      /'; }
    done
fi

sec "links simbólicos"
# Link absoluto aponta para dentro da ISO, não para este computador: /etc/x
# tem que ser conferido como airootfs/etc/x. Sem isso metade dos links do
# systemd é acusada de quebrada e a acusação não quer dizer nada.
quebrados=""
while IFS= read -r -d '' l; do
    alvo=$(readlink "$l")
    case $alvo in
        # /dev/null é MÁSCARA — é assim que se desliga um gerador do systemd,
        # não é um link apontando para o nada.
        /dev/null) continue ;;
        /usr/lib/*) continue ;;
        /*) [[ -e airootfs$alvo ]] && continue ;;
        *)  [[ -e $(dirname "$l")/$alvo ]] && continue ;;
    esac
    quebrados+="$l -> $alvo"$'\n'
done < <(find airootfs -type l -print0)
if [[ -z $quebrados ]]; then ok "nenhum link apontando para o nada"
else bad "links quebrados:"; echo "$quebrados" | sed 's/^/      /'; fi

sec "nada de IFOS sobrando"
# README.md e CLAUDE.md citam o IFOS de propósito: um dá o crédito de onde
# veio o maquinário de hardware, o outro explica a herança para quem for
# mexer aqui. O resto do repositório não pode ter sobra de nome antigo.
resto=$(grep -rIl --exclude-dir=.git --exclude=check.sh \
        --exclude=README.md --exclude=CLAUDE.md \
        -e '\bifos\b' -e '\bIFOS\b' . 2>/dev/null || true)
if [[ -z $resto ]]; then ok "o repositório é só do STYLUS"
else bad "sobrou nome antigo em:"; echo "$resto" | sed 's/^/      /'; fi

sec "coerência interna"
# Todo comando que o dispatcher promete tem que existir.
faltando=()
while read -r sub; do
    [[ -x airootfs/usr/local/bin/$sub ]] || faltando+=("$sub")
done < <(grep -oE 'exec (stylus-[a-z]+)' airootfs/usr/local/bin/stylus | awk '{print $2}' | sort -u)
if (( ${#faltando[@]} == 0 )); then ok "todo stylus-* que o dispatcher chama existe"
else bad "o dispatcher chama o que não existe: ${faltando[*]}"; fi

faltando=()
while read -r py; do
    [[ -f airootfs/usr/share/stylus/tools/$py ]] || faltando+=("$py")
done < <(grep -oE 'TOOLS/[a-z_]+\.py' airootfs/usr/local/bin/stylus | sed 's|TOOLS/||' | sort -u)
if (( ${#faltando[@]} == 0 )); then ok "toda ferramenta python que ele chama existe"
else bad "faltam em tools/: ${faltando[*]}"; fi

for s in airootfs/usr/share/xsessions/*.desktop; do
    exe=$(grep -m1 '^Exec=' "$s" | cut -d= -f2 | awk '{print $1}')
    [[ -f airootfs$exe ]] && ok "sessão $(basename "$s")" || bad "sessão $(basename "$s") aponta para $exe, que não existe"
done

sec "modos de arquivo"
n=0
while IFS= read -r -d '' f; do
    [[ -x $f ]] || { bad "não executável: ${f#./}"; n=$((n+1)); }
done < <(find airootfs/usr/local/bin -type f -print0)
(( n == 0 )) && ok "todo binário em /usr/local/bin é executável"

if (( ! FAST )); then
    sec "nomes de pacote"
    mapfile -t P < <(grep -vE '^\s*#|^\s*$' packages.x86_64)
    ruins=$(LC_ALL=C pacman -Si "${P[@]}" 2>&1 >/dev/null \
            | sed -n 's/^error: package .\(.*\). was not found$/\1/p' | sort -u)
    if [[ -z $ruins ]]; then ok "os ${#P[@]} pacotes existem nos repositórios"
    else bad "não existem:"; echo "$ruins" | sed 's/^/      /'; fi
fi

printf '\n  %s%d passaram%s' "$g" "$PASS" "$z"
(( FAIL )) && printf ', %s%d falharam%s\n\n' "$r" "$FAIL" "$z" || printf '\n\n'
exit $(( FAIL > 0 ))
