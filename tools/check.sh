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
        # /usr/lib e /usr/share vêm de PACOTE: existem dentro da ISO e não
        # aqui. /etc/localtime aponta para o zoneinfo do tzdata, por exemplo.
        /usr/lib/*|/usr/share/*) continue ;;
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
# Sem \b. Com ele esta conferência passava com quatro sobras dentro do
# stylus-controller, porque todas estavam coladas num %s de printf
# ('%sIFOS — controles', '%sifos-update') — e a borda de palavra à esquerda
# não casa entre `s` e `i`. Uma conferência que sempre passa é pior do que
# nenhuma: ela diz que está limpo.
resto=$(grep -rIli --exclude-dir=.git --exclude-dir=work --exclude-dir=out \
        --exclude-dir=.pkgcache --exclude-dir=.claude --exclude=check.sh \
        --exclude=README.md --exclude=CLAUDE.md \
        -e 'ifos' . 2>/dev/null || true)
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

sec "o que o systemd exige para não parar o boot"
# Sem /etc/localtime o systemd-firstboot entra no meio da inicialização e
# PERGUNTA o fuso horário num prompt, na tela, para sempre. A ISO parece
# travada e não está. Custou uma construção inteira para descobrir, e é uma
# linha para conferir.
for f in etc/localtime etc/hostname etc/locale.conf etc/os-release; do
    [[ -e airootfs/$f ]] && ok "$f" || bad "falta airootfs/$f"
done
[[ -e airootfs/etc/passwd ]] && grep -q '^stylus:' airootfs/etc/passwd \
    && ok "o usuário do live medium existe" || bad "sem usuário stylus em /etc/passwd"

sec "nenhuma imagem sobrando de outra distribuição"
# Substituição de texto não alcança PNG: o splash do menu de boot continuou
# dizendo o nome da outra distribuição na primeira ISO, e ele é o primeiro
# quadro que alguém vê.
outra=0
while IFS= read -r -d '' img; do
    rel=${img#./}
    velha="$HOME/Projetos/ifos/${rel//stylus/ifos}"
    if [[ -f $velha ]] && cmp -s "$img" "$velha"; then
        bad "ainda é a arte antiga: $rel"; outra=1
    fi
done < <(find . -path ./work -prune -o -path ./out -prune -o \
              -name '*.png' -print0 2>/dev/null)
(( outra )) || ok "toda a arte é do STYLUS"

sec "modos de arquivo"
n=0
while IFS= read -r -d '' f; do
    [[ -x $f ]] || { bad "não executável: ${f#./}"; n=$((n+1)); }
done < <(find airootfs/usr/local/bin -type f -print0)
(( n == 0 )) && ok "todo binário em /usr/local/bin é executável"

sec "as duas listas de pacote"
# A ISO e a máquina instalada saíram do mesmo repositório e tinham listas
# diferentes: a ISO virou o STYLUS e o instalador continuou instalando a
# distribuição de onde ele veio — com suíte de escritório e sem mpv, sem
# python-pygame, sem nada de música. Ninguém percebeu porque nada conferia.
#
# A regra, agora: todo pacote da ISO está em packages.install OU está em
# packages.live-only com o motivo escrito. Não há terceira opção.
LISTA_ISO=packages.x86_64
LISTA_INST=airootfs/usr/share/stylus/packages.install
LISTA_LIVE=airootfs/usr/share/stylus/packages.live-only
nomes() { grep -vE '^[[:space:]]*#|^[[:space:]]*$' "$1" | tr -s '[:space:]' '\n' | grep -v '^$'; }

if [[ -f $LISTA_INST && -f $LISTA_LIVE ]]; then
    orfaos=$(comm -23 <(nomes "$LISTA_ISO" | sort -u) \
                      <(cat <(nomes "$LISTA_INST") <(nomes "$LISTA_LIVE") | sort -u))
    if [[ -z $orfaos ]]; then ok "toda a ISO ou é instalada, ou tem motivo escrito para não ser"
    else bad "estão na ISO e em lista nenhuma (instale ou justifique em packages.live-only):"
         echo "$orfaos" | sed 's/^/      /'; fi

    velhos=$(comm -13 <(nomes "$LISTA_ISO" | sort -u) <(nomes "$LISTA_LIVE" | sort -u))
    if [[ -z $velhos ]]; then ok "packages.live-only não tem sobra"
    else bad "packages.live-only cita o que a ISO nem tem:"; echo "$velhos" | sed 's/^/      /'; fi

    dois=$(comm -12 <(nomes "$LISTA_INST" | sort -u) <(nomes "$LISTA_LIVE" | sort -u))
    if [[ -z $dois ]]; then ok "nenhum pacote está nas duas listas ao mesmo tempo"
    else bad "está em packages.install E em packages.live-only:"; echo "$dois" | sed 's/^/      /'; fi

    # O instalador LÊ este arquivo. Uma lista vazia ou truncada instalaria uma
    # máquina sem área de trabalho e só diria isso na tela de login que nunca
    # aparece — por isso o instalador também tem um piso, e ele é 100.
    n_inst=$(nomes "$LISTA_INST" | wc -l)
    (( n_inst >= 100 )) && ok "packages.install tem $n_inst nomes" \
        || bad "packages.install tem só $n_inst nomes; o instalador recusa abaixo de 100"
else
    bad "faltam $LISTA_INST e/ou $LISTA_LIVE"
fi

sec "o que o instalador chama e precisa existir"
# O stylus-install chamava /usr/share/stylus/branding-sync.sh, que NÃO EXISTIA
# — e chamava com `|| warn`. A instalação terminava dizendo "concluída" e
# entregava um Arch com i3 sem um comando `stylus` na máquina.
faltando=()
while read -r caminho; do
    [[ -e airootfs$caminho ]] || faltando+=("$caminho")
done < <(grep -ohE '/usr/share/stylus/[A-Za-z0-9_./-]+' \
              airootfs/usr/local/bin/stylus-install | sort -u)
if (( ${#faltando[@]} == 0 )); then ok "todo /usr/share/stylus que o instalador chama existe"
else bad "o instalador chama o que não existe:"; printf '      %s\n' "${faltando[@]}"; fi

sec "multilib no medium ao vivo"
# lib32-gamemode está na lista de TODA máquina, e o /etc/pacman.conf do sistema
# ao vivo não vem do perfil: vem do pacote pacman, onde o multilib está
# comentado. O pacstrap morria em "target not found: lib32-gamemode" DEPOIS de
# formatar o disco. É a razão de existir airootfs/etc/pacman.conf.
precisa32=$(grep -cE '^lib32-' "$LISTA_INST" 2>/dev/null || echo 0)
if (( precisa32 == 0 )); then
    ok "nenhum pacote de 32 bits para instalar"
elif [[ -f airootfs/etc/pacman.conf ]] && \
     grep -qE '^\[multilib\]' airootfs/etc/pacman.conf; then
    ok "o medium ao vivo tem multilib ligado (${precisa32} pacotes de 32 bits)"
else
    bad "packages.install pede ${precisa32} pacotes lib32-* e airootfs/etc/pacman.conf
      não liga o multilib — o pacstrap vai morrer com o disco já formatado"
fi

if (( ! FAST )); then
    sec "nomes de pacote"
    for lista in "$LISTA_ISO" "$LISTA_INST"; do
        [[ -f $lista ]] || continue
        mapfile -t P < <(nomes "$lista")
        ruins=$(LC_ALL=C pacman -Si "${P[@]}" 2>&1 >/dev/null \
                | sed -n 's/^error: package .\(.*\). was not found$/\1/p' | sort -u)
        if [[ -z $ruins ]]; then ok "os ${#P[@]} pacotes de ${lista##*/} existem nos repositórios"
        else bad "${lista##*/} pede o que não existe:"; echo "$ruins" | sed 's/^/      /'; fi
    done
    # Os nomes que o instalador monta na hora (driver de vídeo, hardware
    # detectado) não estão em lista nenhuma: estão escritos dentro do script,
    # e é justamente onde ninguém olha.
    mapfile -t DIN < <(grep -oE '(lib32-)?(nvidia|vulkan|mesa|libva|intel-media|vpl)[a-z0-9-]*' \
                       airootfs/usr/local/bin/stylus-install |
                       grep -vE 'nvidia-(driver|pkg|label|config|suspend|hibernate|resume)' | sort -u)
    mapfile -t HW < <(sed -n '/^HW_PKGS=(/,/^)/p' airootfs/usr/local/bin/stylus-install |
                      sed 's/#.*//' | grep -oE '^\s+[a-z0-9][a-z0-9._+-]*' | tr -d ' ' | sort -u)
    mapfile -t EXTRA < <(printf '%s\n' "${DIN[@]}" "${HW[@]}" broadcom-wl-dkms dkms \
                         archlinux-keyring | sort -u | grep -v '^$')
    ruins=$(LC_ALL=C pacman -Si "${EXTRA[@]}" 2>&1 >/dev/null \
            | sed -n 's/^error: package .\(.*\). was not found$/\1/p' | sort -u)
    if [[ -z $ruins ]]; then ok "os ${#EXTRA[@]} pacotes escolhidos na hora pelo instalador existem"
    else bad "o instalador escolheria o que não existe:"; echo "$ruins" | sed 's/^/      /'; fi
fi

printf '\n  %s%d passaram%s' "$g" "$PASS" "$z"
(( FAIL )) && printf ', %s%d falharam%s\n\n' "$r" "$FAIL" "$z" || printf '\n\n'
exit $(( FAIL > 0 ))
