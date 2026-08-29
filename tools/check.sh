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
# Guardado como o fish e o i3 logo abaixo. Sem a guarda, um computador que não
# tem a ferramenta acusava TODOS os scripts de uma vez — "command not found"
# repetido vinte e sete vezes — e o build.sh, que roda isto antes de construir,
# desistia. (E a linha acima não pode COMEÇAR com o nome da ferramenta depois
# do "#": assim o próprio shellcheck a lê como diretiva e recusa o arquivo.)
if command -v shellcheck >/dev/null; then
    while IFS= read -r -d '' f; do
        head -c 200 "$f" | grep -qE '^#!.*(bash|sh)\b' || continue
        out=$(shellcheck -S warning "$f" 2>&1) && ok "${f#./}" || {
            bad "${f#./}"; echo "$out" | head -6 | sed 's/^/      /'; }
    done < <(find airootfs/usr/local/bin airootfs/usr/share/stylus tools -type f -print0 2>/dev/null)
else
    printf '  %s—%s shellcheck não instalado aqui\n' "$y" "$z"
fi

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

sec "atributos do vinyl que as ferramentas usam"
# `stylus record` chamava vinyl.LIBRARY_ROOT, que NUNCA existiu — o vinyl
# expõe library_root(), uma função. Estourava com AttributeError na primeira
# linha, em toda máquina, num dos comandos do README. A conferência de
# sintaxe passa por cima disso: é erro de execução, não de compilação.
#
# Aqui se importa o vinyl de verdade e se pergunta se cada `vinyl.NOME` que
# as ferramentas escrevem existe mesmo.
if python3 -c 'import numpy' 2>/dev/null; then
    faltando=$(PYTHONPATH=airootfs/usr/share/stylus/deck python3 - <<'PYEOF'
import ast, os, sys
sys.path.insert(0, "airootfs/usr/share/stylus/deck")
try:
    import vinyl
except Exception as e:
    print(f"não deu para importar o vinyl: {e}")
    raise SystemExit(0)

# Pela ÁRVORE, não por expressão regular. A regex casava o nome do ARQUIVO
# ("vinyl.py", citado em comentário) e casava dentro do próprio comentário que
# explica por que vinyl.LIBRARY_ROOT não existe mais — acusando o conserto.
# A árvore só enxerga código.
ruins = []
for base, _d, files in os.walk("airootfs"):
    if "deck/venv" in base:
        continue
    for f in files:
        p = os.path.join(base, f)
        # Não é só .py: o stylus-audio e o stylus-phone são python sem
        # extensão nenhuma, e o stylus-phone usa vinyl. Filtrar por nome
        # deixava justamente os dois comandos maiores de fora da conferência.
        if not f.endswith(".py"):
            try:
                with open(p, "rb") as fh:
                    if b"python" not in fh.readline():
                        continue
            except OSError:
                continue
        try:
            arvore = ast.parse(open(p, encoding="utf-8").read())
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for no in ast.walk(arvore):
            if (isinstance(no, ast.Attribute)
                    and isinstance(no.value, ast.Name)
                    and no.value.id == "vinyl"
                    and not hasattr(vinyl, no.attr)):
                ruins.append(f"{p}:{no.lineno}: vinyl.{no.attr}")
for r in sorted(set(ruins)):
    print(r)
PYEOF
)
    if [[ -z $faltando ]]; then ok "todo vinyl.X que as ferramentas usam existe"
    else bad "usam atributo que o vinyl não tem:"; echo "$faltando" | sed 's/^/      /'; fi
else
    printf '  %s—%s numpy não instalado aqui; o vinyl não pôde ser importado\n' "$y" "$z"
fi

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

sec "a tela cheia, sem tela"
# O deck tinha teste e a interface não — e ela é a CARA da máquina: no modo
# música é a única coisa na tela, e um erro não tratado nela deixa o
# computador preto. Roda com o vídeo "dummy" do SDL, então não precisa de X.
UITEST=airootfs/usr/share/stylus/ui/tools/test_ui.py
# PYGAME_HIDE_SUPPORT_PROMPT: o pygame cumprimenta em stdout ao ser importado,
# e o cumprimento cairia no meio do relatório.
export PYGAME_HIDE_SUPPORT_PROMPT=1
if [[ -f $UITEST ]] && python3 -c 'import pygame' 2>/dev/null; then
    if out=$(python3 "$UITEST" 2>&1); then
        ok "$(grep -oE '[0-9]+ passaram' <<<"$out" | tail -1) na interface"
    else
        bad "a interface tem seção quebrada:"
        grep -E '✗' <<<"$out" | head -6 | sed 's/^/      /'
    fi
else
    printf '  %s—%s pygame não instalado aqui; a interface não foi exercitada\n' "$y" "$z"
fi

sec "o ritual, sem GL"
# **O deck tinha 119 conferências que nada rodava.** O `test_ritual.py` quer
# um álbum de verdade (`--album PASTA`) e, sem ele, escolhe um da estante
# configurada — que num contêiner de construção não existe. Resultado: o
# arquivo que guarda a cerimônia, a contagem de lados, a agulha no sulco e a
# lei do desenho ficava de fora de toda conferência automática, incluindo a
# da nuvem, e só rodava quando alguém lembrava de chamar à mão.
#
# O álbum de mentira sai daqui mesmo: oito WAVs de silêncio escritos pelo
# módulo `wave` do próprio Python. Não precisa de ffmpeg, não toca em coleção
# de ninguém, e some no fim.
RITTEST=airootfs/usr/share/stylus/deck/tools/test_ritual.py
if [[ -f $RITTEST ]] && python3 -c 'import pygame, numpy' 2>/dev/null; then
    RITDIR=$(mktemp -d)
    if python3 - "$RITDIR" <<'WAVEOF'
import os, struct, sys, wave
d = os.path.join(sys.argv[1], "Artista", "Disco")
os.makedirs(d, exist_ok=True)
quadro = struct.pack("<h", 0) * 8000        # um segundo de silêncio
for i in range(1, 9):
    with wave.open(os.path.join(d, "%02d faixa.wav" % i), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(quadro * 180)         # três minutos por faixa
WAVEOF
    then
        if out=$(python3 "$RITTEST" --album "$RITDIR/Artista/Disco" 2>&1); then
            ok "$(grep -oE '[0-9]+ passaram' <<<"$out" | tail -1) no ritual"
        else
            bad "o ritual tem conferência quebrada:"
            grep -E '✗' <<<"$out" | head -6 | sed 's/^/      /'
        fi
    else
        bad "não deu para montar o disco de mentira do teste do ritual"
    fi
    rm -rf "$RITDIR"
else
    printf '  %s—%s pygame/numpy não instalados aqui; o ritual não foi exercitado\n' "$y" "$z"
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
# Três padrões, e cada um existe por um caso real:
#
#   IFOS       maiúsculo, em qualquer posição. Pega '%sIFOS — controles' e o
#              sal '$6$IFOSlive1$' do /etc/shadow. Nenhuma palavra portuguesa
#              tem IFOS maiúsculo no meio.
#   ifos-      minúsculo seguido de hífen: 'ifos-update', 'ifos-controller'.
#   \bifos\b   minúsculo sozinho.
#
# O que NÃO se pode fazer é procurar 'ifos' solto, que foi a primeira tentativa
# aqui: 'glifos' contém 'ifos', e a conferência passou a acusar comentários em
# português. E também não se pode exigir \b dos dois lados, que foi a versão
# original: ela passava com quatro sobras dentro do stylus-controller, porque
# todas estavam coladas num %s de printf e a borda à esquerda não casa entre
# `s` e `i`. Uma conferência que sempre passa é pior do que nenhuma.
resto=$(grep -rIlE --exclude-dir=.git --exclude-dir=work --exclude-dir=out \
        --exclude-dir=.pkgcache --exclude-dir=.claude --exclude=check.sh \
        --exclude-dir=__pycache__ --exclude-dir=build --exclude-dir=.gradle \
        --exclude-dir=node_modules --exclude='.aider*' \
        --exclude=local.properties \
        --exclude=README.md --exclude=CLAUDE.md \
        -e 'IFOS' -e 'ifos-' -e '\bifos\b' . 2>/dev/null || true)
if [[ -z $resto ]]; then ok "o repositório é só do STYLUS"
else bad "sobrou nome antigo em:"; echo "$resto" | sed 's/^/      /'; fi

sec "coerência interna"
# Todo comando que o dispatcher promete tem que existir.
faltando=()
while read -r sub; do
    [[ -x airootfs/usr/local/bin/$sub ]] || faltando+=("$sub")
# O hífen tem que estar na classe: com [a-z]+ o `stylus-side-watch` era cortado
# no primeiro hífen e a conferência acusava um `stylus-side` que ninguém escreveu.
done < <(grep -oE 'exec (stylus-[a-z-]+)' airootfs/usr/local/bin/stylus | awk '{print $2}' | sort -u)
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
# Fora o __pycache__: o `python -m py_compile` deixa .pyc ao lado do arquivo, e
# um .pyc não é para ser executável. Reprovar por causa dele é reprovar por
# causa de lixo de ferramenta, e é assim que se ensina a ignorar a conferência.
n=0
while IFS= read -r -d '' f; do
    [[ -x $f ]] || { bad "não executável: ${f#./}"; n=$((n+1)); }
done < <(find airootfs/usr/local/bin -type f -not -path '*/__pycache__/*' -print0)
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

sec "o que a área de trabalho promete"
# A configuração do i3 e os aliases do fish prometem programas, e ninguém
# conferia se eles existiam. Prometiam três que nunca existiram — stylus-welcome
# (no autostart de toda sessão), stylus-software (no Mod+Shift+A e no alias
# `apps`) e install-stylus (no Mod+Shift+I, que é COMO SE INSTALA o sistema a
# partir do pendrive) — além de abrir o xfce4-terminal, que não está em lista
# de pacote nenhuma, então o Mod+Enter do medium ao vivo não abria nada.
#
# Só a POSIÇÃO DE COMANDO conta: `exec`, `bindsym … exec` e `alias x='cmd'`.
# Um stylus-* dentro de aspas é título de janela ou etiqueta do dunst, não
# programa, e acusá-lo faria a conferência mentir.
i3cmds() {
    sed 's/#.*//' "$@" |
    grep -oE '\bexec(_always)?[[:space:]]+(--no-startup-id[[:space:]]+)?[^,;]*' |
    sed -E 's/^exec(_always)?[[:space:]]+//; s/^--no-startup-id[[:space:]]+//' |
    sed -E 's/^(sudo|setsid)[[:space:]]+//' |
    sed -E 's/^\$term(run)?[[:space:]]+//' |
    sed -E 's/^"[^"]*"[[:space:]]*//' |
    sed -E 's/^sudo[[:space:]]+//' |
    awk '{print $1}'
}
fishcmds() { sed 's/#.*//' "$@" | grep -oE "alias [a-z]+='[^' ]+" | sed "s/.*='//"; }

I3S=(airootfs/etc/skel/.config/i3/config airootfs/usr/share/stylus/i3-music.config)
FISHC=airootfs/etc/skel/.config/fish/conf.d/stylus.fish
mapfile -t PROMETIDOS < <({ i3cmds "${I3S[@]}"; fishcmds "$FISHC"; } | sort -u | grep -v '^$')

faltando=()
for c in "${PROMETIDOS[@]}"; do
    case $c in
        stylus-*|install-*) [[ -f airootfs/usr/local/bin/$c ]] || faltando+=("$c") ;;
    esac
done
if (( ${#faltando[@]} == 0 )); then ok "todo stylus-* que a área de trabalho abre existe"
else bad "a área de trabalho abre o que não existe:"; printf '      %s\n' "${faltando[@]}"; fi

# O terminal, conferido à parte e pelo nome do pacote.
#
# Não dá para conferir TODO programa desta forma: o binário e o pacote têm
# nomes diferentes com frequência (xset vem do xorg-xset, ls do coreutils), e
# uma conferência que confunde as duas coisas acusa o inocente e vira ruído.
# O terminal, porém, é nomeado direto na config e foi ele que quebrou: $term
# era xfce4-terminal, que não está em lista de pacote nenhuma, então o
# Mod+Enter do medium ao vivo não abria nada. Isso dá para conferir exato.
#
# E o do ROFI junto, que é o mesmo defeito no arquivo do lado: a config do i3
# foi consertada com o motivo escrito ao lado dela e o
# `~/.config/rofi/config.rasi` continuou dizendo `terminal: "xfce4-terminal"`.
# É o terminal que o rofi usa para abrir entrada de `Terminal=true` — htop,
# nano, ranger — e o efeito é o pior que existe: clicar e não acontecer nada,
# sem erro em lugar nenhum. Conferir um arquivo e não o vizinho é como este
# defeito sobreviveu ao próprio conserto.
if [[ -f $LISTA_INST ]]; then
    declare -A TERMOS=(
        [i3]="$(sed -n 's/^set \$term  *//p' airootfs/etc/skel/.config/i3/config | awk '{print $1}')"
        [rofi]="$(sed -n 's@^[[:space:]]*terminal:[[:space:]]*"\([^"]*\)".*@\1@p' \
                  airootfs/etc/skel/.config/rofi/config.rasi | awk '{print $1}')"
    )
    for _quem in i3 rofi; do
        _t=${TERMOS[$_quem]}
        if [[ -z $_t ]]; then
            bad "a config do $_quem não diz qual é o terminal"
        elif nomes "$LISTA_INST" | grep -qx "$_t" && nomes "$LISTA_ISO" | grep -qx "$_t"; then
            ok "o terminal do $_quem ($_t) está nas duas listas de pacote"
        else
            bad "o terminal do $_quem é '$_t', que não está nas duas listas — não abre nada"
        fi
    done
fi

sec "nenhuma casa de ninguém escrita à mão"
# Nove ferramentas traziam o caminho da coleção escrito com a casa de UMA
# pessoa dentro (/home/davirazuk/Músicas, e até um subdiretório com o nome da
# coleção dela). Em qualquer outro computador esse caminho não existe — no
# medium ao vivo o usuário é `stylus` — e `stylus covers`, `gaps`, `tags`,
# `check` e `suggest` varriam uma pasta inexistente sem dizer nada de errado.
#
# A raiz da coleção o sistema já sabe: tools/_raiz.py a pergunta ao vinyl.
# Um /home/alguém/ escrito à mão é sempre defeito — fora do _raiz.py e dos
# dois arquivos de documentação, que CITAM o caminho antigo para explicar por
# que ele não pode voltar.
# /home/stylus/ é o usuário que ESTE perfil cria, pelo nome, na hora de montar
# a ISO — o customize_airootfs.sh tem que escrever nele. Qualquer outro nome é
# a casa de uma pessoa que não vai existir no computador de quem usar isto.
casas=$(grep -rIn --exclude-dir=.git --exclude-dir=work --exclude-dir=out \
        --exclude-dir=.pkgcache --exclude-dir=__pycache__ --exclude=check.sh \
        --exclude-dir=.claude --exclude-dir=build --exclude-dir=.gradle \
        --exclude-dir=node_modules --exclude='.aider*' \
        --exclude=local.properties \
        --exclude=_raiz.py --exclude=CLAUDE.md --exclude=README.md \
        -oE '/home/[a-z_][a-z0-9_-]*/' . 2>/dev/null |
        grep -v ':/home/stylus/$' || true)
if [[ -z $casas ]]; then ok "nenhum caminho preso à casa de uma pessoa"
else bad "caminho absoluto para a casa de alguém (use ~ ou tools/_raiz.py):"
     echo "$casas" | sed 's/^/      /' | head -12; fi

sec "arquivos que a área de trabalho aponta"
# keybindings.txt (o Mod+F1) e o papel de parede eram caminhos que não existiam:
# o feh apontava para backgrounds/stylus.png quando o arquivo é
# backgrounds/stylus/stylus.png, então a sessão subia com o fundo cinza do X.
mapfile -t SKELF < <(find airootfs/etc/skel -name __pycache__ -prune -o -type f -print; echo airootfs/usr/share/stylus/i3-music.config)
# O til numa variavel: escrito direto entre aspas ele e so um caractere
# de busca, mas o shellcheck avisa (com razao, em geral) que til entre
# aspas nao expande. Aqui ele NAO deve expandir mesmo - o que se procura
# e o texto que a config do i3 escreve - entao a variavel diz isso sem
# ambiguidade, para o aviso nao virar ruido permanente.
TIL='~'
faltando=()
while read -r caminho; do
    [[ -e airootfs$caminho ]] || faltando+=("$caminho")
done < <(sed 's/#.*//' "${SKELF[@]}" |
         grep -ohE '/usr/share/(stylus|backgrounds)/[A-Za-z0-9_./-]+' |
         sed 's/[.,)]*$//' | sort -u)
while read -r caminho; do
    [[ -e airootfs/etc/skel/${caminho#\~/} ]] || faltando+=("$caminho")
done < <(sed 's/#.*//' airootfs/etc/skel/.config/i3/config |
         grep -ohE "$TIL/[.]config/[A-Za-z0-9_./-]+" | sed 's/[.,)]*$//' | sort -u)
if (( ${#faltando[@]} == 0 )); then ok "todo arquivo que a área de trabalho abre existe"
else bad "apontam para o que não existe:"; printf '      %s\n' "${faltando[@]}"; fi

sec "os arquivos que os comandos chamam existem"
# O stylus-install chamava /usr/share/stylus/branding-sync.sh, que NÃO EXISTIA
# — e chamava com `|| warn`. A instalação terminava dizendo "concluída" e
# entregava um Arch com i3 sem um comando `stylus` na máquina. Agora vale para
# TODO comando, não só para o instalador: era o instalador porque foi lá que
# doeu, e não há motivo para o próximo não doer noutro lugar.
#
# Vale para mais do que /usr/share/stylus. O stylus-lock apontava para
# /usr/share/backgrounds/stylus.png — mas "stylus" ali é uma PASTA, e o
# arquivo é .../stylus/stylus.png. Como todo uso estava atrás de um
# `[[ -f $BG ]]`, nada quebrava: a tela de bloqueio só nunca mostrava o papel
# de parede, em resolução nenhuma, e caía sempre na cor chapada. Um ano
# assim e ninguém nota, porque o defeito é uma coisa que NÃO acontece.
#
# Dois caminhos não existem no repositório de propósito:
#   deck/venv/…   o venv é construído dentro do chroot (o PyOpenGL não está
#                 nos repositórios do Arch), então aqui ele não pode existir.
#   lock/stylus-  é prefixo de nome montado em tempo de execução, não arquivo.
faltando=()
while read -r caminho; do
    # Ponto final colado no fim é pontuação, não nome de arquivo. Um comentário
    # que termina com "…em /usr/share/stylus/venv.sh." fazia esta conferência
    # procurar por "venv.sh." e acusar de faltar um arquivo que está lá — ou
    # seja, o preço de escrever uma frase bem pontuada era um teste vermelho.
    caminho=${caminho%%[.,;:)]}
    case $caminho in
        /usr/share/stylus/deck/venv/*|/usr/share/stylus/lock/stylus-) continue ;;
        # Escrito pelo instalador em tempo de execução, e só quando o
        # plasma-workspace não trouxe um .desktop de sessão X11. Não pode
        # existir aqui: não é nosso, é um remendo para uma versão do Plasma.
        /usr/share/xsessions/plasma.desktop) continue ;;
    esac
    [[ -e airootfs$caminho ]] || faltando+=("$caminho")
done < <(grep -ohE -d skip \
              -e '/usr/share/stylus/[A-Za-z0-9_./-]+' \
              -e '/usr/share/backgrounds/[A-Za-z0-9_./-]+' \
              -e '/usr/share/color-schemes/[A-Za-z0-9_./-]+' \
              -e '/usr/share/xsessions/[A-Za-z0-9_./-]+' \
              -e '/usr/share/applications/stylus[A-Za-z0-9_./-]*' \
              airootfs/usr/local/bin/* | sort -u)
if (( ${#faltando[@]} == 0 )); then ok "todo arquivo do sistema que os comandos chamam pelo nome existe"
else bad "um comando chama o que não existe:"; printf '      %s\n' "${faltando[@]}"; fi

sec "a agulha: quem escreve e quem lê combinam"
# Dois arquivos diferentes, um formato só: o stylus-side-watch grava onde a
# agulha parou e o stylus-deck lê para pôr o disco de volta ali. Se um mudar o
# nome do arquivo ou o número de campos, nada dá erro — o deck simplesmente
# recomeça do zero em silêncio, para sempre, e ninguém liga uma coisa à outra.
escritor=airootfs/usr/local/bin/stylus-side-watch
leitor=airootfs/usr/local/bin/stylus-deck
probs=()
grep -q 'agulha\.tsv' "$escritor" || probs+=("o side-watch não fala em agulha.tsv")
grep -q 'agulha\.tsv' "$leitor"   || probs+=("o deck não fala em agulha.tsv")
# 3 tabulações no write = 4 campos; o leitor desempacota 4 nomes.
n_tab=$(grep -o '\\t' "$escritor" | wc -l)
n_le=$(grep -oE 'read\(\)\.strip\(\)\.split' "$leitor" | wc -l)
(( n_tab == 3 )) || probs+=("o side-watch grava $n_tab tabulações; o formato tem 3")
(( n_le == 1 ))  || probs+=("o deck lê a agulha em $n_le lugares; devia ser 1")
if (( ${#probs[@]} == 0 )); then ok "o formato da agulha bate dos dois lados"
else bad "a agulha ficou desencontrada:"; printf '      %s\n' "${probs[@]}"; fi

sec "o que a tela cheia promete"
# A tela cheia lança comandos por lista de argumentos (as ACOES de cada
# seção). Um nome errado ali não dá erro visível: o painel de saída mostra o
# traceback do Popen e a pessoa conclui que a ferramenta está quebrada, não
# que o nome está. Foi assim que a área de trabalho abria três comandos que
# nunca existiram; a tela cheia merece a mesma conferência.
faltando=()
while read -r cmd; do
    [[ -n $cmd ]] || continue
    [[ -x airootfs/usr/local/bin/$cmd ]] && continue
    command -v "$cmd" >/dev/null && continue
    faltando+=("$cmd")
done < <(python3 - <<'PYEOF'
import ast, sys
arq = "airootfs/usr/share/stylus/ui/app.py"
arvore = ast.parse(open(arq, encoding="utf-8").read(), arq)
vistos = set()
for no in ast.walk(arvore):
    # ["stylus-term", "Título", "stylus-qobuz", "abrir"] e ["stylus", "check"]:
    # o programa é o primeiro item, e o stylus-term recebe o dele no terceiro.
    if not isinstance(no, ast.List) or not no.elts:
        continue
    itens = [e.value for e in no.elts
             if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    if len(itens) != len(no.elts) or not itens:
        continue
    if not itens[0].startswith("stylus"):
        continue
    vistos.add(itens[0])
    if itens[0] == "stylus-term" and len(itens) > 2:
        vistos.add(itens[2])
for v in sorted(vistos):
    print(v)
PYEOF
)
if (( ${#faltando[@]} == 0 )); then ok "todo comando que a tela cheia lança existe"
else bad "a tela cheia lança o que não existe:"; printf '      %s\n' "${faltando[@]}"; fi

sec "o tocador não pode desfazer a tese"
# O mpv LÊ o ~/.config/mpv/mpv.conf, e uma linha herdada de outra máquina —
# `replaygain=track`, `af=loudnorm`, `audio-samplerate=48000` — desfaz o
# caminho bit-perfect ANTES de o som chegar ao PipeWire. O `stylus audio`
# mede do PipeWire para a frente e continuaria dizendo "sem conversão": o
# defeito seria audível e invisível ao mesmo tempo.
#
# A linha de comando ganha do arquivo de configuração, então a defesa é
# passar cada uma explicitamente. Esta conferência existe para que ninguém
# as remova por parecerem redundantes — elas são redundantes até o dia em que
# alguém copia um mpv.conf.
falta=()
for opt in --replaygain=no --af= --volume=100 --audio-samplerate=0 \
           --gapless-audio=yes --audio-display=no; do
    grep -qF -- "$opt" airootfs/usr/local/bin/stylus-deck || falta+=("$opt")
done
if (( ${#falta[@]} == 0 )); then ok "o stylus-deck manda as seis opções que blindam o caminho do sinal"
else bad "o stylus-deck deixou de blindar:"; printf '      %s\n' "${falta[@]}"; fi

sec "as ferramentas que uma ferramenta chama"
# Não é só o dispatcher que chama .py de tools/: o stylus-qobuz chama
# `$TOOLS/run_queue_api.py`, e esse por sua vez chama `integrate_album.py` e
# `embed_metadata.py` pelo nome, com cwd na própria pasta. Um nome errado aí
# não dá erro na hora — dá no meio da fila, depois de o disco já ter baixado,
# que é o pior momento possível para descobrir.
faltando=()
while read -r py; do
    [[ -f airootfs/usr/share/stylus/tools/$py ]] || faltando+=("$py")
done < <({ grep -ohE -d skip '\$TOOLS/[a-z_]+\.py' airootfs/usr/local/bin/* \
             | sed 's|\$TOOLS/||'
           # Só o que é invocado como programa: [sys.executable, "x.py", ...].
           grep -ohE '\[sys\.executable, "[a-z_]+\.py"' \
                airootfs/usr/share/stylus/tools/*.py \
             | sed 's|.*"\(.*\)"|\1|'
           grep -ohE 'python3 [a-z_]+\.py' \
                airootfs/usr/share/stylus/tools/*.sh 2>/dev/null \
             | sed 's|python3 ||'; } | sort -u)
if (( ${#faltando[@]} == 0 )); then ok "toda ferramenta que outra ferramenta chama existe"
else bad "chamam .py que não existe em tools/:"; printf '      %s\n' "${faltando[@]}"; fi

sec "os lançadores do menu"
# Um .desktop com Exec para um comando que não existe some do menu sem erro
# nenhum — o rofi simplesmente não o lista, e não há onde ler o porquê.
faltando=()
for lanc in airootfs/usr/share/applications/*.desktop; do
    [[ -e $lanc ]] || continue
    linha=$(grep -m1 '^Exec=' "$lanc") || { faltando+=("$(basename "$lanc"): sem Exec="); continue; }
    # O primeiro campo é o programa; o resto são argumentos e pode ser
    # qualquer coisa (inclusive aspas, que é o caso do stylus-term).
    prog=${linha#Exec=}; prog=${prog%% *}
    [[ -x airootfs/usr/local/bin/$prog ]] || command -v "$prog" >/dev/null \
        || faltando+=("$(basename "$lanc") -> $prog")
done
if (( ${#faltando[@]} == 0 )); then
    ok "todo .desktop do menu abre um comando que existe"
else bad "lançador apontando para o que não existe:"; printf '      %s\n' "${faltando[@]}"; fi

sec "o branding-sync entrega o STYLUS inteiro"
# Não confere por leitura: RODA o branding-sync para uma pasta temporária e
# olha o que caiu lá. É a única conferência do repositório que executa a coisa
# de verdade, e existe porque a lista de permissão dele é escrita à mão — ela
# trazia só a unidade do celular, e a do lado do disco, acrescentada depois,
# ficava para trás em silêncio: numa máquina instalada o aviso de virar o lado
# simplesmente nunca chegava.
#
# Tudo que é `stylus*` em /usr/local/bin e toda unidade de usuário TÊM que
# chegar. E o que é só do medium ao vivo NÃO pode chegar: o sudo sem senha e o
# usuário `stylus` do pendrive dentro da máquina de alguém são um defeito de
# segurança, não um esquecimento.
tmp=$(mktemp -d)
mkdir -p "$tmp/usr" "$tmp/etc"
if STYLUS_SOURCE=airootfs bash airootfs/usr/share/stylus/branding-sync.sh "$tmp" >/dev/null 2>&1; then
    faltando=(); vazou=()
    while read -r f; do
        [[ -e $tmp/${f#airootfs/} ]] || faltando+=("${f#airootfs/}")
    done < <({ find airootfs/usr/local/bin -maxdepth 1 -name 'stylus*'
               # Duas buscas e não uma: `find A -name X -o -path Y` só desce em
               # A, então o -path das unidades nunca casava e a metade que esta
               # conferência existe para pegar não era conferida.
               find airootfs/usr/lib/systemd/user -maxdepth 1 -name 'stylus-*.service' 2>/dev/null; })
    for f in usr/share/stylus/claude/CLAUDE.md usr/share/stylus/packages.install \
             etc/skel/.config/i3/config etc/os-release etc/pipewire; do
        [[ -e $tmp/$f ]] || faltando+=("$f")
    done
    for f in etc/sudoers.d/10-stylus-live etc/sysusers.d/stylus.conf \
             etc/tmpfiles.d/stylus-home.conf etc/mkinitcpio.conf.d/archiso.conf \
             usr/local/bin/choose-mirror usr/local/bin/livecd-sound; do
        [[ -e $tmp/$f ]] && vazou+=("$f")
    done
    if (( ${#faltando[@]} == 0 && ${#vazou[@]} == 0 )); then
        ok "$(find "$tmp/usr/local/bin" -name 'stylus*' | wc -l) comandos e $(find "$tmp/usr/lib/systemd/user" -name '*.service' 2>/dev/null | wc -l) unidades chegam, e nada do medium vaza"
    else
        (( ${#faltando[@]} )) && { bad "o branding-sync não leva:"; printf '      %s\n' "${faltando[@]}"; }
        (( ${#vazou[@]} ))    && { bad "o branding-sync leva o que é só do medium:"; printf '      %s\n' "${vazou[@]}"; }
    fi
else
    bad "o branding-sync falhou ao copiar para uma pasta de teste"
fi
rm -rf "$tmp"

sec "os serviços que a instalação liga"
# O script que roda no chroot usa `set -e`, e `systemctl enable` de unidade
# inexistente SAI COM ERRO — depois do pacstrap, com o disco já formatado e
# antes do grub-install. Ou seja: máquina que não liga.
#
# Foi o que quase saiu daqui: a impressão foi tirada da lista de pacotes e o
# `systemctl enable cups.socket` ficou para trás. Esta conferência liga o nome
# da unidade ao pacote que a traz.
declare -A DONO=(
    [NetworkManager.service]=networkmanager  [bluetooth.service]=bluez
    [sddm.service]=sddm                      [ufw.service]=ufw
    [paccache.timer]=pacman-contrib          [earlyoom.service]=earlyoom
    [rtkit-daemon.service]=rtkit             [cups.socket]=cups
    [power-profiles-daemon.service]=power-profiles-daemon
    [nvidia-suspend.service]=nvidia-utils    [nvidia-hibernate.service]=nvidia-utils
    [nvidia-resume.service]=nvidia-utils
)
faltando=()
while read -r unidade; do
    # As nossas vêm do airootfs, não de pacote.
    if [[ $unidade == stylus-* ]]; then
        [[ -e airootfs/etc/systemd/system/$unidade ]] || faltando+=("$unidade (nossa, e o arquivo não existe)")
        continue
    fi
    # systemd e util-linux vêm com o `base`; não precisam de linha na lista.
    case $unidade in systemd-*|fstrim.timer) continue ;; esac
    pkg=${DONO[$unidade]:-}
    if [[ -z $pkg ]]; then
        faltando+=("$unidade (ninguém sabe que pacote traz — acrescente em DONO)")
    elif ! nomes "$LISTA_INST" | grep -qx "$pkg"; then
        faltando+=("$unidade <- $pkg, que não está em packages.install")
    fi
done < <(sed -n '/stylus-configure.sh/,/^CHROOT$/p' airootfs/usr/local/bin/stylus-install |
         # Sem comentários: eles CITAM unidades para explicar por que uma
         # saiu (o cups.socket é o exemplo), e citar não é ligar.
         sed 's/#.*//' |
         # Junta as linhas continuadas com "\\" ANTES de filtrar: o
         # `systemctl enable` do NVIDIA quebra em duas, e o `|| true` que o
         # torna inofensivo mora na segunda — filtrando linha a linha, a
         # primeira parecia desprotegida e a conferência acusava o inocente.
         sed -e :a -e '/\\$/{N;s/\\\n//;ba}' |
         # E sem as linhas que já toleram falhar: uma unidade ligada com
         # `|| true` ou `2>/dev/null` não derruba nada se faltar, que é
         # exatamente o caso das do NVIDIA, ligadas só quando há placa.
         grep -v '|| true' | grep -v '2>/dev/null' |
         grep -oE 'systemctl enable [a-z0-9@.-]+( [a-z0-9@.-]+)*' |
         sed 's/systemctl enable //' | tr ' ' '\n' |
         grep -E '\.(service|socket|timer|target)$' | sort -u)
if (( ${#faltando[@]} == 0 )); then ok "toda unidade que a instalação liga vem de um pacote instalado"
else bad "a instalação liga o que pode não existir:"; printf '      %s\n' "${faltando[@]}"; fi

sec "o `stylus --help` diz tudo que o `stylus` aceita"
# O despachante tinha 63 nomes no `case` e 34 no texto de ajuda. Vinte e nove
# comandos que existiam e que ninguém tinha como descobrir: `stylus big`,
# `stylus loja`, `stylus glifos`, `stylus números`… Cada um deles é uma linha
# que precisa continuar funcionando para sempre e que nunca é usada, porque
# nunca foi anunciada.
#
# A regra agora é simples: se o `case` atende, a ajuda diz. Ou documenta, ou
# apaga — o que não pode é existir escondido.
naodoc=()
ajuda=$(sed -n '/^usage()/,/^EOF$/p' airootfs/usr/local/bin/stylus)
while read -r tok; do
    [[ -z $tok ]] && continue
    # -h/--help/help se explicam sozinhos e não entram na própria lista.
    case $tok in -h|--help|help) continue ;; esac
    grep -qE "(^|[^a-z-])${tok}([^a-z-]|$)" <<<"$ajuda" || naodoc+=("$tok")
done < <(grep -oE '^    [a-z|áéíóúâê-]+\)' airootfs/usr/local/bin/stylus |
         tr -d ' )' | tr '|' '\n' | sort -u)
if (( ${#naodoc[@]} == 0 )); then
    ok "os $(grep -oE '^    [a-z|áéíóúâê-]+\)' airootfs/usr/local/bin/stylus | tr -d ' )' | tr '|' '\n' | grep -vc '^$') nomes que o stylus aceita estão todos na ajuda"
else
    bad "o stylus aceita nomes que a ajuda não menciona:"
    printf '      %s\n' "${naodoc[@]}"
fi

# ── a paleta e o theme.py dizem a mesma coisa ─────────────────────────────
# O cabeçalho do arquivo `palette` diz, com todas as letras, que a fonte da
# verdade é o ui/theme.py. Nada conferia isso — e as duas já discordavam: o
# INK_DEEP existia na paleta e não no theme.py. Um arquivo que se declara
# cópia de outro e não é conferido volta a derivar, que é o defeito inteiro
# que a paleta existe para não deixar acontecer.
sec "a paleta é o theme.py"
divergem=$(python3 - <<'DUOEOF'
import re
pal = {}
for ln in open("airootfs/usr/share/stylus/palette", encoding="utf-8"):
    m = re.match(r"^([A-Z_]+)=#([0-9a-fA-F]{6})\s*$", ln)
    if m:
        pal[m.group(1)] = m.group(2).lower()
th = {}
for ln in open("airootfs/usr/share/stylus/ui/theme.py", encoding="utf-8"):
    m = re.match(r"^([A-Z_]+)\s*=\s*\((\d+),\s*(\d+),\s*(\d+)\)", ln)
    if m:
        th[m.group(1)] = "%02x%02x%02x" % tuple(int(m.group(i)) for i in (2, 3, 4))
for k in sorted(set(pal) | set(th)):
    a, b = pal.get(k), th.get(k)
    if a != b:
        print(f"{k}: palette=#{a or 'não tem'} theme.py=#{b or 'não tem'}")
DUOEOF
)
if [[ -z $divergem ]]; then
    ok "as duas listas de cor são a mesma lista"
else
    bad "a paleta e o theme.py discordam:"
    printf '%s\n' "$divergem" | sed 's/^/      /'
fi

sec "a paleta não derivou"
# **Sintoma:** nenhum. E é esse o problema.
#
# As cores estavam copiadas à mão em sete arquivos e tinham derivado devagar:
# o texto era #e8ecf5 na tela cheia e #e2e7f0 na barra; o azul, #5bcefa no
# rofi e #70c8e8 na polybar; o lavanda, #b7a0ff aqui e #b090f0 ali. Havia até
# dois pretos "mais fundos que o fundo" a duas unidades um do outro.
#
# Nenhuma dessas diferenças aparece quando se olha um arquivo por vez — só
# quando se olha o sistema. O resultado não é "uma cor errada": é a barra, o
# menu e a tela cheia parecendo vir de três projetos diferentes.
#
# A regra: uma cor no /etc/skel ou é IGUAL a uma da paleta, ou é claramente
# outra cor. O que não pode existir é quase-igual — que é sempre engano, nunca
# escolha. As variantes claras do terminal (o azul brilhante do ANSI, por
# exemplo) ficam longe o bastante e passam.
deriva=$(python3 - <<'PALEOF'
import re, pathlib

pal = {}
for linha in open("airootfs/usr/share/stylus/palette", encoding="utf-8"):
    m = re.match(r"^([A-Z_]+)=#([0-9a-fA-F]{6})$", linha.strip())
    if m:
        pal[m.group(1)] = m.group(2).lower()


def rgb(h):
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


LIMITE = 22.0        # abaixo disto, duas cores sao a mesma intencao

# Os dois lados da casa. O i3 mora no /etc/skel; o KDE, em /usr/share --
# esquema de cor, Kvantum, qt5ct/qt6ct. Uma paleta que so vale de um lado
# nao e uma paleta: e a barra do i3 e o Dolphin do KDE discordando sobre
# qual e o cinza do sistema, que e exatamente o que se quer evitar quando
# duas pessoas usam a mesma maquina de jeitos diferentes.
# `airootfs/etc` inteiro e nao so o `/etc/skel`: havia uma SEGUNDA arvore da
# polybar em `/etc/polybar`, com nove dos dez arquivos diferentes da do skel e
# a paleta VELHA dentro (#e2e7f0, #5c6478, #b090f0, #70c8e8 — as cores que o
# cabecalho do arquivo `palette` cita pelo nome como exemplo de deriva). Ela
# passou verde por anos porque esta conferencia so olhava o /etc/skel.
# E as DUAS TELAS QUE VÊM ANTES DA ÁREA DE TRABALHO: o GRUB e o login. Elas
# estavam inteiras na paleta velha — #e2e7f0, #7e899c, #0d0f14 — mais um
# amarelo e um rosa do Catppuccin (#f9e2af, #f38ba8) e um verde-menta que não
# existe em lugar nenhum deste sistema. E o nome STYLUS, que é âmbar em todo
# canto, aparecia em AZUL na primeira tela que alguém vê da máquina.
RAIZES = ["airootfs/etc",
          "airootfs/usr/share/sddm",
          "airootfs/usr/share/grub",
          "airootfs/usr/share/color-schemes",
          "airootfs/usr/share/Kvantum",
          "airootfs/usr/share/qt5ct",
          "airootfs/usr/share/qt6ct",
          # E o celular. A coleção é a mesma dos dois lados, e a promessa do
          # sistema é que ela SE PARECE a mesma. O app tinha dezesseis cores
          # quase-iguais às do computador e usava o âmbar do Material
          # (#ffc107) em cinco lugares onde vai o âmbar do STYLUS.
          "android/app/src/main"]

achados = {}


def confere(cor, r, arq):
    for nome, v in pal.items():
        d = sum((a - b) ** 2 for a, b in zip(r, rgb(v))) ** 0.5
        if 0 < d < LIMITE:
            achados.setdefault(f"{cor} esta a {d:.0f} de {nome} (#{v})", set()).add(
                str(arq).replace("airootfs/", ""))
            return


for raiz in RAIZES:
    for arq in pathlib.Path(raiz).rglob("*"):
        if not arq.is_file() or arq.suffix in (".svg", ".png", ".webp", ".jar"):
            continue
        try:
            txt = arq.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # 8 digitos = cor com transparencia; o prefixo de alfa nao e cor.
        for m in re.finditer(r"#([0-9a-fA-F]{8})\b|#([0-9a-fA-F]{6})\b"
                             r"|0[xX][fF][fF]([0-9a-fA-F]{6})\b", txt):
            h = (m.group(1)[2:] if m.group(1)
                 else (m.group(2) or m.group(3))).lower()
            if h not in pal.values():
                confere(f"#{h}", rgb(h), arq)
        # O KDE escreve cor como "R,G,B" decimal, nao como hex.
        for m in re.finditer(r"^\s*[A-Za-z][A-Za-z0-9]*\s*=\s*(\d{1,3}),(\d{1,3}),(\d{1,3})\s*$",
                             txt, re.M):
            r = tuple(int(x) for x in m.groups())
            if any(x > 255 for x in r):
                continue
            if "%02x%02x%02x" % r in pal.values():
                continue
            confere("%d,%d,%d" % r, r, arq)
for k in sorted(achados):
    print(k + "  em  " + ", ".join(sorted(achados[k])[:3]))
PALEOF
)
if [[ -z $deriva ]]; then
    ok "as $(grep -cE '^[A-Z_]+=#' airootfs/usr/share/stylus/palette) cores da paleta valem no i3, no KDE e no celular"
else
    bad "cor quase-igual a uma da paleta (deriva):"
    printf '      %s\n' "$deriva"
fi

sec "a sessão X11 do KDE tem gerenciador de janelas"
# **Sintoma:** o KDE instala, abre, mostra o painel e a área de trabalho — e
# não dá para arrastar, redimensionar nem fechar uma janela. O alt+tab não faz
# nada. Nenhum atalho do KDE funciona. Nada no registro reclama.
#
# O KDE separou o KWin em dois pacotes: `kwin` passou a ser o compositor do
# WAYLAND, e o gerenciador de janelas do X11 saiu para `kwin-x11`. O
# plasma-workspace depende do `kwin` — o de Wayland — e NADA depende do
# kwin-x11. Este sistema é X11, então instalar "plasma-desktop
# plasma-workspace" entrega uma área de trabalho sem gerenciador de janelas.
#
# E o que mais atrapalhou: `command -v startplasma-x11` continua respondendo
# que sim, porque ele vem do plasma-workspace. Toda conferência que perguntava
# "o Plasma está instalado?" dizia que sim.
#
# O plasma-x11-session são quatro arquivos e depende do kwin-x11: pedir por
# ele é pedir a sessão X11 inteira.
# Por VIZINHANÇA, e medida em CÓDIGO. Duas versões erradas antes desta:
#
#   por arquivo   "o arquivo cita plasma-x11-session em algum lugar?" — passava
#                 com o defeito de volta, porque o stylus-install também
#                 imprime uma dica de instalação trezentas linhas abaixo.
#                 Citar em outro lugar não instala.
#   por linha     contando linhas do arquivo — e o comentário que explica POR
#                 QUE o pacote está ali empurrava o próprio pacote para fora
#                 da janela. A conferência acusava a lista que ela mesma
#                 tinha acabado de aprovar.
#
# Comentário e linha em branco saem antes de medir; o que sobra é a lista de
# pacotes como o shell a vê.
sem_wm=()
while IFS= read -r arquivo; do
    # `grep -n .` não serve: o sed acima apaga o TEXTO do comentário e deixa a
    # indentação, e uma linha só de espaços casa com ".". Os comentários
    # continuavam ocupando a janela, que é justamente o que se quer evitar.
    mapfile -t cod < <(sed 's/#.*//' "$arquivo" | grep -n '[^[:space:]]')
    for i in "${!cod[@]}"; do
        linha=${cod[i]#*:}
        # Âncora no plasma-desktop, e NÃO no plasma-workspace. Toda lista que
        # instala o KDE tem os dois; mas o plasma-workspace também é citado em
        # mensagens do tipo "isto vem do pacote plasma-workspace", e ali não
        # há lista nenhuma para conferir. Ancorando nos dois, o stylus-wallpaper
        # foi acusado por explicar de onde vem um binário.
        [[ $linha == *plasma-desktop* ]] || continue
        achou=0
        for (( j = i > 6 ? i - 6 : 0; j <= i + 8 && j < ${#cod[@]}; j++ )); do
            viz=${cod[j]#*:}
            [[ $viz == *plasma-x11-session* || $viz == *kwin-x11* ]] && { achou=1; break; }
        done
        (( achou )) || sem_wm+=("${arquivo#airootfs/}, linha ${cod[i]%%:*}")
    done
done < <(grep -rl 'plasma-desktop' airootfs/usr/local/bin 2>/dev/null | sort)
if (( ${#sem_wm[@]} == 0 )); then
    ok "todo lugar que instala o Plasma instala também o gerenciador de janelas do X11"
else
    bad "instala o Plasma sem gerenciador de janelas para o X11 (falta plasma-x11-session):"
    printf '      %s\n' "${sem_wm[@]}"
fi

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

if (( ! FAST )) && ! command -v pacman >/dev/null; then
    sec "nomes de pacote"
    # Sem pacman não dá para conferir nome nenhum — e o jeito como isto estava
    # escrito NÃO dizia isso: `pacman -Si ... | sed -n 's/^error: package…'`
    # com o pacman ausente produz "command not found", que o sed não casa, o
    # que deixa a lista de ruins vazia, o que imprime "os 239 pacotes existem
    # nos repositórios". Uma conferência que aprova tudo num computador que não
    # tem como conferir nada é pior do que não ter conferência: ela mente.
    printf '  %s—%s pacman não existe aqui; use --fast, ou rode numa máquina Arch\n' "$y" "$z"
elif (( ! FAST )); then
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
    #
    # Só o que o instalador INSTALARIA. Duas categorias precisam ficar de fora
    # ou a conferência acusa o inocente:
    #   - `nvidia` sozinho, que aqui é o nome de uma ESCOLHA (GPU_CHOICE), não
    #     de um pacote;
    #   - os ramos legacy da AUR (580xx/470xx/390xx), que o instalador cita
    #     pelo nome de propósito e nunca instala — ele oferece o nouveau.
    # Sem os comentários: eles CITAM nomes de pacote para explicar por que não
    # se usa mais aquele nome, e citar não é instalar.
    mapfile -t DIN < <(sed 's/#.*//' airootfs/usr/local/bin/stylus-install |
                       grep -oE '(lib32-)?(nvidia|vulkan|mesa|libva|intel-media|vpl)[a-z0-9-]*' |
                       grep -vE 'nvidia-(driver|pkg|label|config|suspend|hibernate|resume)' |
                       grep -vxE 'nvidia|libva' |
                       grep -vE 'nvidia-[0-9]+xx-dkms' | sort -u)
    mapfile -t HW < <(sed -n '/^HW_PKGS=(/,/^)/p' airootfs/usr/local/bin/stylus-install |
                      sed 's/#.*//' |
         # Junta as linhas continuadas com "\\" ANTES de filtrar: o
         # `systemctl enable` do NVIDIA quebra em duas, e o `|| true` que o
         # torna inofensivo mora na segunda — filtrando linha a linha, a
         # primeira parecia desprotegida e a conferência acusava o inocente.
         sed -e :a -e '/\\$/{N;s/\\\n//;ba}' | grep -oE '^\s+[a-z0-9][a-z0-9._+-]*' | tr -d ' ' | sort -u)
    mapfile -t EXTRA < <(printf '%s\n' "${DIN[@]}" "${HW[@]}" broadcom-wl-dkms dkms \
                         archlinux-keyring | sort -u | grep -v '^$')
    ruins=$(LC_ALL=C pacman -Si "${EXTRA[@]}" 2>&1 >/dev/null \
            | sed -n 's/^error: package .\(.*\). was not found$/\1/p' | sort -u)
    if [[ -z $ruins ]]; then ok "os ${#EXTRA[@]} pacotes escolhidos na hora pelo instalador existem"
    else bad "o instalador escolheria o que não existe:"; echo "$ruins" | sed 's/^/      /'; fi
fi

# ── nos aplicativos Qt, dá para LER o que está escrito ────────────────────
# **Sintoma:** rótulo preto sobre fundo preto, e campo de texto com o fundo em
# âmbar chapado.
#
# O `/usr/share/qt5ct/colors/stylus.conf` é uma lista de vinte cores SEM NOME
# numa ordem que só o Qt conhece (o enum QPalette::ColorRole), e as cores
# estavam nos papéis errados: WindowText tinha a mesma cor de Window, e Base —
# o fundo de campo de texto, lista e tabela — era o âmbar da seleção. Ler o
# arquivo não pega nada: são vinte hexadecimais numa linha. Vê-se abrindo um
# aplicativo Qt, e é o tipo de coisa que a pessoa atribui ao aplicativo.
#
# A conferência é sobre o RESULTADO, não sobre a cor escolhida: texto e fundo
# do mesmo par têm que estar longe um do outro. Quem escrever outra paleta
# amanhã pode escolher o que quiser, menos escrever no escuro.
sec "os aplicativos Qt e o KDE dão para ler"
ilegivel=$(python3 - <<'QTEOF'
import pathlib

PAPEIS = ("WindowText Button Light Midlight Dark Mid Text BrightText "
          "ButtonText Base Window Shadow Highlight HighlightedText Link "
          "LinkVisited AlternateBase NoRole ToolTipBase ToolTipText").split()
# (o que se escreve, sobre o quê) — os pares que existem na tela.
PARES = [("WindowText", "Window"), ("Text", "Base"), ("Text", "AlternateBase"),
         ("ButtonText", "Button"), ("HighlightedText", "Highlight"),
         ("ToolTipText", "ToolTipBase"), ("Link", "Base"),
         ("LinkVisited", "Base")]
# Longe o bastante para se ler. Não é contraste WCAG — é o piso abaixo do
# qual as duas cores são a mesma mancha.
PISO = 90.0


def rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 8:            # aarrggbb
        h = h[2:]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


for arq in sorted(pathlib.Path("airootfs/usr/share").glob("qt*ct/colors/*.conf")):
    for linha in arq.read_text(encoding="utf-8").splitlines():
        if "_colors" not in linha or "=" not in linha:
            continue
        estado, valores = linha.split("=", 1)
        cores = [v.strip() for v in valores.split(",")]
        if len(cores) < len(PAPEIS):
            print("%s: %s tem %d cores, o Qt espera %d"
                  % (arq.name, estado, len(cores), len(PAPEIS)))
            continue
        m = dict(zip(PAPEIS, cores))
        for frente, fundo in PARES:
            a, b = rgb(m[frente]), rgb(m[fundo])
            d = sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
            if d < PISO:
                print("%s %s: %s (%s) sobre %s (%s) — distância %.0f"
                      % (arq.parent.parent.name, estado.strip(), frente,
                         m[frente], fundo, m[fundo], d))
QTEOF
)
# E o esquema do KDE junto. Ali as cores TÊM nome, o que é o motivo de ele
# estar certo — mas nada conferia, e "as cores têm nome" não é garantia:
# quem escrever um `[Colors:Selection]` novo com o âmbar no fundo e o âmbar
# na frente não vê nada de errado lendo o que escreveu.
ilegivel_kde=$(python3 - <<'KDEEOF'
import pathlib, re

PISO = 90.0


def rgb(v):
    return tuple(int(x) for x in v.split(",")[:3])


for arq in sorted(pathlib.Path("airootfs/usr/share/color-schemes").glob("*.colors")):
    secao, fundo = None, {}
    frente = {}
    for linha in arq.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        m = re.match(r"^\[(Colors:[A-Za-z]+)\]$", linha)
        if m:
            secao = m.group(1)
            continue
        if secao and "=" in linha and not linha.startswith("#"):
            chave, valor = linha.split("=", 1)
            if chave == "BackgroundNormal":
                fundo[secao] = rgb(valor)
            elif chave in ("ForegroundNormal", "ForegroundLink",
                           "ForegroundActive"):
                frente.setdefault(secao, {})[chave] = rgb(valor)
    for secao, papeis in sorted(frente.items()):
        b = fundo.get(secao)
        if b is None:
            print("%s %s: sem BackgroundNormal" % (arq.name, secao))
            continue
        for chave, a in sorted(papeis.items()):
            d = sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
            if d < PISO:
                print("%s %s: %s sobre o fundo — distância %.0f"
                      % (arq.name, secao, chave, d))
KDEEOF
)
if [[ -z $ilegivel && -z $ilegivel_kde ]]; then
    ok "qt5ct, qt6ct e o esquema do KDE: texto legível sobre o fundo"
else
    bad "tema escrevendo no escuro:"
    printf '%s\n' "$ilegivel" "$ilegivel_kde" | grep -v '^$' | sed 's/^/      /'
fi

# ── função escrita e nunca chamada ────────────────────────────────────────
# É a armadilha mais cara deste repositório, e ela já apareceu cinco vezes:
#
#   · o `set_text` das duas legendas do deck — as camadas eram criadas e
#     desenhadas em todo quadro, e ninguém as alimentava: o deck nunca disse
#     "vire o disco", que é a tese do sistema;
#   · o `Nx` do diário e a fileira "OS QUE VOLTAM" que dependia dele;
#   · o "X min encostado no móvel" da pilha, atrás de um `if` nunca verdadeiro;
#   · o `get_position` do scrobbler, que era a resposta para "quanto disso
#     você ouviu de verdade" e nunca era chamado (e estava quebrado);
#   · o `tem_conta` do Qobuz, que era uma TERCEIRA opinião sobre uma pergunta
#     que já tinha dono.
#
# Quando achar um ajudante que ninguém chama, desconfie de um recurso inteiro
# faltando. Ler não pega: a função existe, tem nome bom e faz alguma coisa.
sec "nenhuma função escrita e nunca chamada"
orfas=$(python3 - <<'ORFAEOF'
import ast
import os
import re

# Onde procurar as definições.
alvos = []
for raiz, ds, fs in os.walk("airootfs"):
    ds[:] = [d for d in ds if d != "__pycache__"]
    for f in fs:
        p = os.path.join(raiz, f)
        if f.endswith(".py"):
            alvos.append(p)
        elif "/bin/" in p:
            try:
                if open(p, "rb").read(30).startswith(b"#!/usr/bin/env python"):
                    alvos.append(p)
            except OSError:
                pass

# E o repositório INTEIRO onde procurar os usos: uma função pode ser chamada
# de um script de shell, de um teste ou de um `python3 -c`.
#
# Contado UMA vez, num Counter, e não com um `re.findall` por função: são
# mais de mil funções contra alguns megabytes de texto, e a forma ingênua
# fazia o check.sh inteiro passar de dez segundos para quase dois minutos.
import collections

BINARIOS = (".png", ".jpg", ".jpeg", ".webp", ".ico", ".gz", ".xz", ".zip",
            ".jar", ".ttf", ".otf", ".pyc", ".so", ".bin", ".img", ".pdf")
usos = collections.Counter()
for raiz, ds, fs in os.walk("."):
    ds[:] = [d for d in ds if d not in (".git", "__pycache__", "work", "out",
                                        "node_modules", "build", ".gradle")]
    for f in fs:
        if f.lower().endswith(BINARIOS):
            continue
        try:
            conteudo = open(os.path.join(raiz, f), encoding="utf-8",
                            errors="ignore").read()
        except OSError:
            continue
        # `\w+` e não `[A-Za-z_]\w*`: há função com acento no nome
        # (`coleção_de_mentira`), e o recorte ASCII a partia em dois — o
        # nome inteiro nunca aparecia na contagem e ela era acusada de órfã.
        usos.update(re.findall(r"\w+", conteudo))

# Nomes que existem para serem chamados de fora e por isso podem aparecer
# uma vez só: pontos de entrada e ganchos que o Python chama sozinho.
LIVRES = {"main", "test"}

for p in sorted(alvos):
    try:
        fonte = open(p, encoding="utf-8").read()
        arv = ast.parse(fonte)
    except (OSError, SyntaxError):
        continue
    linhas = fonte.splitlines()
    for no in ast.walk(arv):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        n = no.name
        if n.startswith("__") or n in LIVRES:
            continue
        # `# noqa: orfa` na linha do def: para o dia em que uma função for
        # chamada de um jeito que este texto não vê.
        if "noqa: orfa" in linhas[no.lineno - 1]:
            continue
        if usos[n] <= 1:
            print("%s:%d  %s()" % (p.replace("airootfs/", ""), no.lineno, n))
ORFAEOF
)
if [[ -z $orfas ]]; then
    ok "toda função definida é chamada em algum lugar"
else
    bad "função escrita e nunca chamada (recurso faltando?):"
    printf '%s\n' "$orfas" | sed 's/^/      /'
fi

# ── o scrobble conta o que você OUVIU ─────────────────────────────────────
# Dois defeitos que se escondiam um no outro, e os dois no mesmo formato de
# playerctl:
#
#   1. A DURAÇÃO ERA SEMPRE ZERO. O formato pedido era
#      `{{duration(mpris:length)}}`, e `duration()` é o ajudante que FORMATA
#      microssegundos em "3:42" — o `isdigit()` logo abaixo dava falso e a
#      duração virava 0. Com ela zerada, o limiar caía sempre nos 4 minutos
#      fixos: nenhuma música de menos de quatro minutos era scroblada nunca,
#      que é metade do que se ouve.
#   2. O CONTADOR ERA RELÓGIO DE PAREDE. `time.time() - track_start`, e o
#      docstring prometendo que "pausar e voltar não reseta o contador" —
#      o que acontecia era pior: pausar não PARAVA o contador. Almoço com a
#      música pausada scroblava a faixa sem ninguém ter ouvido nada.
#
# O `get_position`, que responderia isso, existia e NUNCA era chamado — e
# estava quebrado do mesmo jeito (`{{position(mpris:position)}}` devolve
# "2:05"). Helper que ninguém chama costuma ser um recurso inteiro faltando.
sec "o scrobble conta o que você ouviu"
scr=$(python3 - <<'SCROBEOF'
import importlib.machinery as _im
import importlib.util as _iu
import sys
import types

falso = types.ModuleType("subprocess")
falso.SubprocessError = type("SubprocessError", (Exception,), {})
_resp = {"saida": "", "rc": 0}


class _R:
    def __init__(self):
        self.stdout, self.returncode, self.stderr = _resp["saida"], _resp["rc"], ""


falso.run = lambda *a, **k: _R()
sys.modules["subprocess"] = falso

spec = _iu.spec_from_loader("scrob", _im.SourceFileLoader(
    "scrob", "airootfs/usr/local/bin/stylus-scrobble"))
mod = _iu.module_from_spec(spec)
spec.loader.exec_module(mod)
del sys.modules["subprocess"]

erros = []

# ── a duração: uma faixa de 3:42 tem que valer 222 s, não 0 ──────────────
_resp["saida"] = "Radiohead\nOK Computer\nLet Down\n222000000\n"
t = mod.get_now_playing()
if not t or t["duration"] != 222:
    erros.append("duração de 3:42 veio %r" % (t and t.get("duration"),))
# E o limiar que sai dela: metade, não os 4 minutos fixos.
d = (t or {}).get("duration", 0)
limiar = min(240, max(0, d // 2)) if d else 240
if limiar != 111:
    erros.append("o limiar de uma faixa de 3:42 deu %s (esperado 111)" % limiar)

# Formato antigo ("3:42") não pode virar um número enorme por acidente.
_resp["saida"] = "A\nB\nC\n3:42\n"
if (mod.get_now_playing() or {}).get("duration") != 0:
    erros.append("um texto formatado virou duração")

# ── a posição: segundos com decimal, e None quando não dá ────────────────
_resp["saida"] = "125.32\n"
if mod.get_position() != 125.32:
    erros.append("posição veio %r" % (mod.get_position(),))
_resp["saida"] = "sem posição\n"
if mod.get_position() is not None:
    erros.append("posição ilegível não devolveu None")
_resp["saida"], _resp["rc"] = "12.0\n", 1
if mod.get_position() is not None:
    erros.append("playerctl falhando não devolveu None")
_resp["rc"] = 0

# ── quanto se ouviu entre duas voltas ────────────────────────────────────
P = mod.PASSO
casos = [
    ("tocando normal", 10.0, 10.0 + P, P),
    ("pausado", 10.0, 10.0, 0.0),
    ("busca para frente", 10.0, 200.0, 0.0),
    ("busca para trás", 200.0, 10.0, 0.0),
    ("sem posição", None, None, P),
    ("posição sumiu no meio", 10.0, None, P),
]
for nome, antes, agora, esperado in casos:
    got = mod.ouviu_quanto(antes, agora)
    if abs(got - esperado) > 1e-6:
        erros.append("%s: %.2f (esperado %.2f)" % (nome, got, esperado))

# E o que se PEDE ao playerctl, que um subprocess de mentira não tem como
# conferir: ele devolve o mesmo texto seja qual for o formato pedido. Os
# dois defeitos deste arquivo estavam justamente no formato, então esta
# metade é lida da fonte.
# Pela ÁRVORE e não por um grep no texto: os comentários deste arquivo
# citam a forma errada de propósito, para explicar o defeito. O que se
# confere é o que vai dentro das chamadas ao subprocess.run.
import ast

pedidos = []
for no in ast.walk(ast.parse(
        open("airootfs/usr/local/bin/stylus-scrobble", encoding="utf-8").read())):
    if not isinstance(no, ast.Call):
        continue
    alvo = no.func
    if not (isinstance(alvo, ast.Attribute) and alvo.attr == "run"):
        continue
    for a in ast.walk(no):
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            pedidos.append(a.value)
juntos = " ".join(pedidos)
if "duration(mpris:length)" in juntos:
    erros.append("a duração ainda é pedida FORMATADA (devolve '3:42')")
if "{{mpris:length}}" not in juntos:
    erros.append("a duração não é pedida crua ({{mpris:length}})")
if "position(mpris:position)" in juntos:
    erros.append("a posição ainda é pedida FORMATADA (devolve '2:05')")

for e in erros:
    print(e)
SCROBEOF
)
if [[ -z $scr ]]; then
    ok "duração lida em microssegundos, e o contador congela na pausa"
else
    bad "o scrobbler conta errado:"
    printf '%s\n' "$scr" | sed 's/^/      /'
fi

# ── a barra fala do disco também quando ele vem da rede ───────────────────
# **Sintoma:** com uma playlist do Qobuz tocando, o módulo do disco na barra
# ficava em BRANCO — nada de "LADO A · 3/5 · vira em 12 min", que é o motivo
# de aquele arquivo existir.
#
# O `playing_path` recusava o endereço com um `os.path.isfile` antes de
# qualquer outra coisa. E o caminho já existia inteiro do outro lado: o
# `vinyl.resolve_album` trata `http(s)://` desde sempre, achando pelo `eid=`
# a pasta de cache que descreve a lista. Faltava deixar o endereço CHEGAR
# nele — as duas metades prontas, o fio entre elas faltando.
sec "a barra reconhece o disco que vem da rede"
barra=$(python3 - <<'BARRAEOF'
import importlib.machinery as _im
import importlib.util as _iu
import os
import sys
import types

# Um vinyl de mentira: o album.py sai na hora se não conseguir importar um.
falso = types.ModuleType("vinyl")
falso.Session = lambda: None
falso.resolve_album = lambda p: None
falso.Album = lambda *a, **k: None
falso.track_index_for = lambda *a, **k: -1
falso.log_play = lambda *a, **k: None
sys.modules["vinyl"] = falso

alvo = "airootfs/etc/skel/.config/polybar/scripts/album.py"
spec = _iu.spec_from_loader("albmod", _im.SourceFileLoader("albmod", alvo))
mod = _iu.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except SystemExit:
    print("o album.py saiu ao ser carregado")
    raise SystemExit(0)


class _Sessao:
    def __init__(self, caminho):
        self.caminho = caminho

    def snapshot(self):
        return {"path": self.caminho}


casos = [
    ("https://streaming.qobuz.com/file?eid=123", True, "endereço do Qobuz"),
    ("/nao/existe/faixa.flac", False, "arquivo que não existe"),
    ("", False, "nada tocando"),
    (os.path.abspath(alvo), True, "arquivo que existe"),
]
for caminho, esperado, nome in casos:
    mod._session = _Sessao(caminho)
    tem = mod.playing_path() is not None
    if tem != esperado:
        print("%s: playing_path devolveu %s" % (nome, mod.playing_path()))

# E o rótulo do lado não pode ser lido com colchete: o lado único de uma
# playlist já derrubou a tela cheia por isso.
# (linhas de comentário fora: esta conferência é sobre o código, e o
# comentário que explica o defeito cita a forma errada de propósito.)
for n_l, linha in enumerate(open(alvo, encoding="utf-8"), 1):
    nu = linha.split("#", 1)[0]
    if 'side["label"]' in nu or "side['label']" in nu:
        print("linha %d: o rótulo do lado é lido com colchete (use .get)"
              % n_l)
BARRAEOF
)
if [[ -z $barra ]]; then
    ok "o disco da rede chega ao módulo da barra, e o lado usa .get"
else
    bad "o módulo do disco na barra:"
    printf '%s\n' "$barra" | sed 's/^/      /'
fi

# ── o que conta como música é UMA lista ───────────────────────────────────
# **Sintoma:** `stylus covers`, `stylus suggest` e o gerador de playlist não
# achavam faixa nenhuma numa coleção em ALAC, Opus ou Vorbis — e não davam
# erro: diziam "0 capas a escrever", "nenhuma sugestão", playlist vazia.
#
# Havia QUATRO listas de extensão neste sistema e elas já discordavam: o
# vinyl tinha oito com .wma, o check_library e o discover tinham oito com
# .shn e sem .wma, e o extract_covers, o embed_metadata, o make_new_playlist
# e o suggest_playlists paravam em .flac e .mp3. É o mesmo estrago do
# `/home/davirazuk/Músicas` escrito à mão em nove ferramentas — só que em vez
# de varrer a pasta errada, elas varriam a pasta certa procurando o formato
# errado. A resposta mora no `_raiz.audio_ext()`, que pergunta ao vinyl.
sec "o que conta como música é uma lista só"
listas=$(python3 - <<'EXTEOF'
import pathlib, re

# Uma tupla de extensões de áudio escrita à mão fora do vinyl e do _raiz.
# DUAS ou mais extensões: um `endswith(".flac")` sozinho é uma rotina que
# só existe para o FLAC, e isso é legítimo — não é uma opinião sobre o que
# conta como música.
padrao = re.compile(r'\(\s*"\.(?:flac|mp3|ogg|opus|m4a|wav|aac|wma|shn)"'
                    r'(?:\s*,\s*"\.[a-z0-9]+")+\s*,?\s*\)')
# E os comandos do /usr/local/bin junto: o `stylus-phone` tinha a QUINTA
# cópia da lista, sem o .shn — uma coleção de gravação ao vivo no celular
# era invisível para o `stylus phone`.
livres = {"_raiz.py"}
alvos = list(pathlib.Path("airootfs/usr/share/stylus/tools").glob("*.py"))
for a in sorted(pathlib.Path("airootfs/usr/local/bin").iterdir()):
    if a.is_file() and a.read_bytes()[:21].startswith(b"#!/usr/bin/env python"):
        alvos.append(a)
for arq in sorted(alvos):
    if arq.name in livres:
        continue
    for n, linha in enumerate(arq.read_text(encoding="utf-8").splitlines(), 1):
        nu = linha.lstrip()
        if nu.startswith("#"):
            continue
        # "o que eu sei ESCREVER" é outra pergunta que não "o que é música",
        # e uma ferramenta tem direito a respondê-la — desde que diga isso
        # no nome. Ver o ESCREVIVEIS do embed_metadata.
        if "ESCREV" in nu.split("=")[0]:
            continue
        if padrao.search(linha):
            print("%s:%d  %s" % (arq.name, n, linha.strip()[:70]))
EXTEOF
)
if [[ -z $listas ]]; then
    ok "nenhuma ferramenta traz a própria lista de extensões"
else
    bad "lista de extensões escrita à mão (use o _raiz.audio_ext):"
    printf '%s\n' "$listas" | sed 's/^/      /'
fi

sec "a capa embutida é achada em todo formato"
# O `extract_covers` só sabia ler .flac e .mp3. Cada formato guarda a capa
# num lugar diferente — o átomo `covr` do MP4, o `metadata_block_picture` do
# Ogg (um bloco PICTURE do FLAC em base64 dentro de uma tag de texto) — e a
# ferramenta simplesmente não fazia nada, dizendo "0 não têm capa embutida".
#
# O FLAC é conferido com um arquivo DE VERDADE, montado aqui (cabeçalho
# fLaC + STREAMINFO, sem quadros de áudio: o mutagen só lê metadado). Os
# outros dois não dá para montar sem codificador, então o teste entrega ao
# `embedded_art` o objeto que o mutagen entregaria — que é onde mora a
# lógica que quebrou.
capas=$(python3 - <<'CAPAEOF'
import base64, os, struct, sys, tempfile

sys.path.insert(0, "airootfs/usr/share/stylus/tools")
tmp = tempfile.mkdtemp(prefix="stylus-capa-")
os.environ.setdefault("STYLUS_LIBRARY", tmp)

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4Cover
import extract_covers as EC

erros = []


def flac_minimo(caminho):
    si = bytearray(34)
    struct.pack_into(">HH", si, 0, 4096, 4096)
    v = (44100 << 44) | (1 << 41) | (15 << 36) | 0     # 44,1k estéreo 16 bits
    si[10:18] = v.to_bytes(8, "big")
    cab = bytes([0x80]) + len(si).to_bytes(3, "big")   # último bloco, tipo 0
    open(caminho, "wb").write(b"fLaC" + cab + bytes(si))


alvo = os.path.join(tmp, "t.flac")
flac_minimo(alvo)
f = FLAC(alvo)
p = Picture()
p.type, p.mime, p.data = 3, "image/png", b"\x89PNG\r\n\x1a\n" + b"x" * 40
f.add_picture(p)
f.save()
r = EC.embedded_art(alvo)
if not r or r[1] != ".png" or len(r[0]) != 48:
    erros.append("FLAC de verdade: %r" % (r,))


class _Arq:
    pictures = None

    def __init__(self, tags):
        self.tags = tags


og = Picture()
og.type, og.mime, og.data = 3, "image/jpeg", b"\xff\xd8" + b"o" * 30
casos = [
    ("Ogg/Opus", _Arq({"metadata_block_picture":
                       [base64.b64encode(og.write()).decode("ascii")]}),
     ".jpg", 32),
    ("MP4/ALAC", _Arq({"covr": [MP4Cover(b"\x89PNG" + b"m" * 30,
                                         imageformat=MP4Cover.FORMAT_PNG)]}),
     ".png", 34),
    ("sem capa", _Arq({}), None, 0),
]
verdadeiro = mutagen.File
try:
    for nome, obj, ext, n in casos:
        mutagen.File = lambda _p, _o=obj: _o
        r = EC.embedded_art("qualquer")
        if ext is None:
            if r is not None:
                erros.append("%s: inventou capa %r" % (nome, r))
        elif not r or r[1] != ext or len(r[0]) != n:
            erros.append("%s: %r" % (nome, r))
finally:
    mutagen.File = verdadeiro

import shutil
shutil.rmtree(tmp, ignore_errors=True)
for e in erros:
    print(e)
CAPAEOF
)
if [[ -z $capas ]]; then
    ok "capa achada em FLAC, MP4/ALAC e Ogg/Opus (e nenhuma inventada)"
else
    bad "o extrator de capas não lê todo formato:"
    printf '%s\n' "$capas" | sed 's/^/      /'
fi

# ── a cerimônia é UMA só, nos dois lugares ────────────────────────────────
# O deck e a tela cheia do lançador encenam o MESMO ritual — spinup → cue →
# drop. As durações moram no `vinyl.py`, e o `app.py` as lê de lá em vez de
# trazer três números parecidos escritos à mão. É a deriva da paleta outra
# vez, em segundos no lugar de hexadecimais: pôr um disco no deck e pôr um
# disco no lançador não podem virar dois gestos com durações diferentes.
sec "o deck e o lançador encenam a mesma cerimônia"
mesma=$(python3 - <<'CEREOF'
import pathlib, re

app = pathlib.Path("airootfs/usr/share/stylus/ui/app.py").read_text()
for nome, cte in (("CER_SPIN", "SPINUP_T"), ("CER_CUE", "CUE_T"),
                  ("CER_DROP", "DROP_T")):
    m = re.search(r"^\s*%s\s*=\s*(.+)$" % nome, app, re.M)
    if m is None:
        print("%s sumiu do app.py" % nome)
    elif cte not in m.group(1):
        print("%s não vem do vinyl.%s: %s" % (nome, cte, m.group(1).strip()))
CEREOF
)
if [[ -z $mesma ]]; then
    ok "as 3 durações da cerimônia vêm do vinyl.py"
else
    bad "o lançador tem uma cerimônia própria:"
    printf '%s\n' "$mesma" | sed 's/^/      /'
fi

# ── a lei do desenho do vinil, escrita em números ─────────────────────────
# A §5.5 do CLAUDE.md diz que o disco é FÓSFORO e não plástico: preto frio no
# corpo, âmbar como única cor viva. Ela já custou semanas, e o jeito de ela
# ser desfeita não é alguém discordando dela — é alguém "melhorando o visual"
# e pondo um especular branco de volta, que é o que qualquer referência de
# toca-discos na internet mostra.
#
# A seção de paleta do vinyl.py se chamava, ela mesma, "vinyl is plastic, not
# phosphor", e mandava o oposto da lei: especular BRANCO, sulcos cinzas
# QUENTES, intervalos QUASE-BRANCOS. Ficou assim por meses depois de o braço
# já ter virado luz. Escrever a lei em números é o que impede a próxima volta.
sec "no deck, o que é luz é âmbar e o que é corpo é frio"
fora_da_lei=$(python3 - <<'LUZEOF'
import re, pathlib

txt = pathlib.Path("airootfs/usr/share/stylus/deck/vinyl.py").read_text()
cor = {}
for nome, r, g, b in re.findall(
        r"^([A-Z_]+)\s*=\s*\(([\d.]+),\s*([\d.]+),\s*([\d.]+)\)", txt, re.M):
    cor[nome] = (float(r), float(g), float(b))

# O que é LUZ no quadro: tem que ser claramente âmbar — vermelho bem acima do
# azul. Branco (r≈b) reprova, e é exatamente o que estava escrito.
luz = ("VINYL_RIM", "SHEEN", "GROOVE_PLAYED", "GROOVE_GAP", "EDGE_RING",
       "STYLUS_HOT", "ARM_LIGHT", "ARM_TIP", "ALARM")
# O que é CORPO: preto frio. O azul não pode ficar abaixo do vermelho.
frio = ("VINYL_CORE", "GROOVE_UNPLAYED", "DUST")

for nome in luz:
    if nome not in cor:
        print("%s: sumiu da paleta" % nome)
        continue
    r, g, b = cor[nome]
    if r <= b * 1.5:
        print("%s = (%.3f, %.3f, %.3f): é luz e não é âmbar "
              "(vermelho tem que passar de 1,5× o azul)" % (nome, r, g, b))
for nome in frio:
    if nome not in cor:
        print("%s: sumiu da paleta" % nome)
        continue
    r, g, b = cor[nome]
    if b < r:
        print("%s = (%.3f, %.3f, %.3f): é corpo e está QUENTE "
              "(o azul não pode ficar abaixo do vermelho)" % (nome, r, g, b))
LUZEOF
)
if [[ -z $fora_da_lei ]]; then
    ok "as 12 cores do disco seguem a §5.5"
else
    bad "a paleta do deck saiu da lei do desenho (CLAUDE.md §5.5):"
    printf '%s\n' "$fora_da_lei" | sed 's/^/      /'
fi

# ── os dois terminais são o mesmo terminal ────────────────────────────────
# **Sintoma:** o STYLUS tem dois terminais — o alacritty no i3 e o Konsole no
# KDE — e eles tinham paletas DIFERENTES. O do i3 usava as cores do arquivo
# `palette`; o do KDE usava um esquema próprio, com vermelho 200,80,80 onde a
# paleta diz 238,122,130 e azul 0,102,204 onde ela diz 91,206,250.
#
# A conferência da paleta logo acima não pegava: ela varre o /etc/skel e
# compara HEXADECIMAL, e este esquema mora dentro de um heredoc num script do
# /usr/local/bin escrito em R,G,B decimal. Dois formatos e dois lugares é
# exatamente onde a deriva se esconde.
sec "o Konsole e o alacritty têm as mesmas cores"
difere=$(python3 - <<'TERMEOF'
import re, pathlib

ala = pathlib.Path("airootfs/etc/skel/.config/alacritty/alacritty.toml").read_text()
kde = pathlib.Path("airootfs/usr/local/bin/stylus-switch-kde").read_text()


def hexa(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def bloco(texto, nome):
    m = re.search(r"^\[colors\.%s\]\n((?:\w+\s*=.*\n)+)" % nome, texto, re.M)
    return dict(re.findall(r"(\w+)\s*=\s*\"(#[0-9a-fA-F]{6})\"", m.group(1)))


prim = bloco(ala, "primary")
nor = bloco(ala, "normal")
bri = bloco(ala, "bright")

# O esquema do Konsole, de dentro do heredoc.
esq = {}
for sec_, cor in re.findall(r"^\[(\w+)\]\nColor=(\d+,\d+,\d+)$", kde, re.M):
    esq[sec_] = tuple(int(v) for v in cor.split(","))

ordem = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
esperado = {"Background": prim["background"], "Foreground": prim["foreground"]}
for i, nome in enumerate(ordem):
    esperado["Color%d" % i] = nor[nome]
    esperado["Color%dIntense" % i] = bri[nome]

for chave in sorted(esperado, key=lambda k: (len(k), k)):
    quer = hexa(esperado[chave])
    tem = esq.get(chave)
    if tem is None:
        print("%s: o Konsole não define" % chave)
    elif tem != quer:
        print("%s: alacritty=%s Konsole=%s"
              % (chave, ",".join(str(v) for v in quer),
                 ",".join(str(v) for v in tem)))
TERMEOF
)
if [[ -z $difere ]]; then
    ok "as 18 cores do Konsole são as do alacritty"
else
    bad "os dois terminais do sistema discordam:"
    printf '%s\n' "$difere" | sed 's/^/      /'
fi

# ── módulo de barra escrito e nunca desenhado ─────────────────────────────
# **Sintoma:** nenhum, e é sempre esse o sintoma desta família.
#
# O `[module/webdav]` estava escrito, tinha script próprio, acendia em verde
# quando o celular estava montado e dizia quantas pastas vieram — e não
# aparecia em NENHUMA das três linhas `modules-*`. A barra nunca o desenhou.
# Quem rodava `stylus webdav` não tinha, na tela, nenhuma confirmação de que
# tinha dado certo; o `[module/xwindow]` estava no mesmo estado.
#
# É a mesma família do `stylus-welcome` que o i3 abria e não existia: as duas
# metades escritas, o fio entre elas faltando. Ler um arquivo por vez não
# pega — o defeito só existe na relação entre as duas listas.
sec "toda peça da barra é desenhada"
sobrando=$(python3 - <<'BAREOF'
import re, pathlib
cfg = pathlib.Path("airootfs/etc/skel/.config/polybar/config.ini")
texto = cfg.read_text(encoding="utf-8")
definidos = set(re.findall(r"^\[module/([\w-]+)\]", texto, re.M))
usados = set()
for ln in re.findall(r"^modules-[\w-]+\s*=(.*)$", texto, re.M):
    usados.update(ln.split())
# `sep-*` são espaçadores; existir sem ser usado ali seria o mesmo defeito,
# então eles NÃO são exceção. A exceção seria um módulo herdado por outra
# barra, e não há outra barra neste arquivo.
for m in sorted(definidos - usados):
    print(m)
falta = sorted(usados - definidos)
for m in falta:
    print("!" + m)
BAREOF
)
if [[ -z $sobrando ]]; then
    ok "todo [module/…] da polybar está numa linha modules-*"
else
    bad "a polybar tem peça escrita e não desenhada (ou o contrário):"
    printf '%s\n' "$sobrando" | sed 's/^!/      NÃO EXISTE: /; s/^\([^ ]\)/      nunca desenhado: \1/'
fi

# ── o que o --help escreve é texto que a pessoa lê ────────────────────────
# A regra do projeto é: texto que o usuário vê é em português; comentário
# acompanha o arquivo em que está. O docstring de um módulo é as DUAS coisas
# — o argparse o imprime como descrição do `--help`. Quatro ferramentas
# alcançáveis pelo `stylus` tinham o seu em inglês, e uma delas falava do
# dono da máquina na terceira pessoa e pelo nome.
sec "o que as ferramentas escrevem está em português"
ingles=$(python3 - <<'ENEOF'
import ast, glob, os, re
# Palavras que não existem em português. Nada de "files" ou "list", que
# aparecem citando nome de arquivo ou de comando.
ing = re.compile(r"\b(the|and|with|from|this|that|which|without|instead|"
                 r"these|there|when|your|into|already|every|would|wrote|"
                 r"found|missing|scanned|entries|nothing|untouched)\b", re.I)
for f in sorted(glob.glob("airootfs/usr/share/stylus/tools/*.py")):
    try:
        arv = ast.parse(open(f, encoding="utf-8").read())
    except Exception:                       # noqa: BLE001
        continue
    # O docstring, que o argparse imprime como descrição do --help…
    d = ast.get_docstring(arv) or ""
    n = len(ing.findall(d))
    if n >= 4:
        print(f"{os.path.basename(f)}: --help ({n} palavras)")
    # …e o que o programa ESCREVE enquanto roda, que é texto que a pessoa lê
    # do mesmo jeito. Só as strings dentro de print(): comentário e nome de
    # variável seguem o arquivo, e isso a regra permite.
    for no in ast.walk(arv):
        if not (isinstance(no, ast.Call) and getattr(no.func, "id", "") == "print"):
            continue
        for arg in no.args:
            pedacos = []
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                pedacos = [arg.value]
            elif isinstance(arg, ast.JoinedStr):
                pedacos = [v.value for v in arg.values
                           if isinstance(v, ast.Constant) and isinstance(v.value, str)]
            texto = " ".join(pedacos)
            if len(ing.findall(texto)) >= 1:
                print(f"{os.path.basename(f)}:{no.lineno}: {texto.strip()[:46]!r}")
ENEOF
)
if [[ -z $ingles ]]; then
    ok "o --help e a saída das ferramentas estão em português"
else
    bad "estas ferramentas falam inglês com o usuário:"
    printf '%s\n' "$ingles" | sed 's/^/      /'
fi


# ── `stylus X --help` não pode FAZER o X ──────────────────────────────────
# **Sintoma:** o `--help` era repassado ao programa de baixo, e vários não
# sabem o que é. `stylus backup --help` FAZIA UM BACKUP e largava um .tar.gz
# na casa da pessoa; `stylus reindex --help` relia a estante inteira;
# `stylus aur --help` mexia no yay. O gesto universal de "me explique antes
# de eu executar" era exatamente o que executava.
#
# A casa é falsa e descartável: se um subcomando voltar a AGIR no --help, o
# estrago cai no /tmp e a conferência flagra o arquivo que ele deixou lá —
# em vez de a própria conferência sujar a casa de quem a roda.
sec "nenhum --help faz o trabalho"
CASA_FALSA=$(mktemp -d)
agiram=""
for c in $(sed 's/#.*//' airootfs/usr/local/bin/stylus |
           grep -oE '^\s+[a-z][a-z|]*\)' | tr -d ' )' | tr '|' '\n' |
           grep -vxE 'h|help' | sort -u); do
    antes=$(find "$CASA_FALSA" -type f 2>/dev/null | wc -l)
    saida=$(HOME="$CASA_FALSA" XDG_CONFIG_HOME="$CASA_FALSA/.config" \
            XDG_DATA_HOME="$CASA_FALSA/.local/share" \
            XDG_CACHE_HOME="$CASA_FALSA/.cache" \
            STYLUS_SHARE="$PWD/airootfs/usr/share/stylus" \
            timeout 10 bash airootfs/usr/local/bin/stylus "$c" --help 2>&1)
    rc=$?
    depois=$(find "$CASA_FALSA" -type f 2>/dev/null | wc -l)
    if (( rc == 124 )); then
        agiram+=" $c(travou)"
    elif (( depois > antes )); then
        agiram+=" $c(escreveu-arquivo)"
    elif [[ -z ${saida// } ]]; then
        agiram+=" $c(mudo)"
    fi
done
rm -rf "$CASA_FALSA"
if [[ -z $agiram ]]; then
    ok "todo subcomando sabe se explicar sem executar nada"
else
    bad "--help executa ou emudece em:$agiram"
fi


# ── ler o clone do sistema sem esbarrar no dono ───────────────────────────
# **Sintoma:** a tela de AJUSTES mostrava a data da ISO no lugar da versão
# instalada. O /var/lib/stylus/repo é do root — o stylus-update roda com
# sudo — e o git recusa ler repositório de outro dono desde a 2.35.6
# ("detected dubious ownership"). O erro vai para o stderr, o stdout vem
# vazio, e quem chamou cai num plano B sem perceber que falhou.
#
# Isso quebra o laço de trabalho do sistema: publicar, `stylus-update`,
# conferir se chegou. Quem responde "qual versão eu tenho" respondia sempre a
# mesma coisa, e a resposta parecia plausível.
#
# A primeira versão desta conferência procurava `git ... -C .../repo` numa
# linha só — e passou verde com o defeito de volta, porque no python o "git"
# e o "-C" estão em LINHAS diferentes, que é exatamente o arquivo onde o
# problema estava. Conferência que não reprova o defeito conhecido não é
# conferência. Agora a regra é por ARQUIVO: quem cita o clone e chama git tem
# que dizer safe.directory em algum lugar.
sec "quem lê o clone do sistema passa o safe.directory"
faltando=""
for f in $(grep -rl '/var/lib/stylus/repo' airootfs/usr/local/bin \
                     airootfs/usr/share/stylus 2>/dev/null); do
    # O stylus-update fica de fora: ele é quem CRIA o clone e roda com sudo,
    # então o dono bate e o git não reclama. safe.directory ali seria enfeite.
    [[ ${f##*/} == stylus-update ]] && continue
    grep -q 'git' "$f" || continue
    grep -q 'safe\.directory' "$f" || faltando+="$f"$'\n'
done
if [[ -z $faltando ]]; then
    ok "todo git que abre /var/lib/stylus/repo diz de quem ele é"
else
    bad "git em /var/lib/stylus/repo sem safe.directory (vai falhar calado):"
    printf '%s' "$faltando" | sed 's/^/      /'
fi

# ── a lista de atalhos não pode mentir ────────────────────────────────────
# **Sintoma:** o Mod+F1 dizia "mudar o foco (ou Mod+H J K L)". O Mod+L
# TRANCA A TELA. Quem seguia a própria ajuda do sistema para mover o foco
# para a direita trancava a sessão — e o atalho de verdade, o Mod+;, não
# estava escrito em lugar nenhum.
#
# Uma ajuda errada é pior do que ajuda nenhuma: ela é lida como verdade e
# ninguém confere. Então cada tecla que a ajuda cita para focar/mover tem que
# estar ligada, no config, ao comando que a ajuda promete.
sec "a lista de atalhos bate com o i3"
CFG=airootfs/etc/skel/.config/i3/config
AJUDA=airootfs/usr/share/stylus/keybindings.txt
if [[ -f $CFG && -f $AJUDA ]]; then
    erros=""
    # As teclas do vim que a ajuda anuncia entre parênteses, na ordem
    # esquerda-baixo-cima-direita.
    citadas=$(grep -oE '\(ou Mod\+(Shift\+)?[A-Z; ]+\)' "$AJUDA" | head -2)
    for par in "focus:mudar o foco" "move:mover a janela"; do
        acao=${par%%:*}
        # o que o config liga de fato àquela ação
        mapfile -t teclas < <(grep -oE "^bindsym \\\$mod\+(Shift\+)?[a-z]+ ${acao} (left|down|up|right)" "$CFG" |
                              sed -E "s/^bindsym \\\$mod\+(Shift\+)?//; s/ ${acao}.*//" | sort -u)
        for t in "${teclas[@]}"; do
            # ponto-e-vírgula aparece na ajuda como o próprio caractere
            mostra=$t; [[ $t == semicolon ]] && mostra=";"
            [[ ${#mostra} -gt 1 ]] && continue     # setas, escritas em prosa
            grep -qiF "$mostra" <<<"$citadas" || erros+=" $acao/$mostra"
        done
    done
    # E o inverso, que é o defeito que aconteceu: uma tecla anunciada que na
    # verdade está ligada a OUTRA coisa.
    # Tira o "Mod+" e o "Shift+" ANTES de extrair as letras: sem isso o M de
    # "Mod" e o S de "Shift" entram na lista e a conferência acusa duas
    # teclas que a ajuda nunca prometeu.
    for letra in $(grep -oE '\(ou Mod\+(Shift\+)?[A-Z; ]+\)' "$AJUDA" |
                   sed -E 's/\(ou Mod\+(Shift\+)?//; s/\)//' |
                   grep -oE '[A-Z;]' | sort -u); do
        alvo=$letra; [[ $letra == ";" ]] && alvo=semicolon
        min=$(tr '[:upper:]' '[:lower:]' <<<"$alvo")
        linha=$(grep -E "^bindsym \\\$mod\+(Shift\+)?${min} " "$CFG" | head -1)
        [[ -z $linha ]] && { erros+=" $letra(nao-ligada)"; continue; }
        grep -qE ' (focus|move) (left|down|up|right)$' <<<"$linha" ||
            erros+=" $letra(e-outra-coisa)"
    done
    if [[ -z $erros ]]; then
        ok "as teclas que o Mod+F1 anuncia fazem o que ele promete"
    else
        bad "o Mod+F1 mente sobre:$erros"
    fi
else
    printf '  %s—%s sem config do i3 ou sem keybindings.txt\n' "$y" "$z"
fi

# ── quem pede root não pode perder o que ia fazer ─────────────────────────
# **Sintoma:** `stylus app yay` imprimia o menu e não instalava nada. Idem
# clonehero e heroic — todo aplicativo que precisa de root, que são quase
# todos.
#
# O `precisa_root` era chamado de dentro de `app_yay` como `precisa_root
# "$@"`, e ali `$@` são os argumentos da FUNÇÃO — o despachante chama
# `"app_$a"` sem nenhum. O `exec sudo -E "$0" "$@"` relançava o script com a
# linha de comando VAZIA, e sem argumento o stylus-app faz exatamente uma
# coisa: imprime a lista e sai com zero. Nada falhava e nada avisava.
#
# Ler não pega isso — as duas formas são shell válido e parecem iguais. Então
# a conferência EXECUTA o comando com um `sudo` de mentira e olha o que
# chegaria do outro lado.
sec "o pedido de root não engole o comando"
if [[ -x airootfs/usr/local/bin/stylus-app ]]; then
    falso=$(mktemp -d); chmod 0755 "$falso"
    printf '#!/bin/bash\necho "SUDO: $*"\nexit 0\n' > "$falso/sudo"
    chmod 0755 "$falso/sudo"
    # Esta conferência só existe se quem a roda NÃO for root. Como root o
    # `precisa_root` volta na hora, o `app_yay` segue em frente, e o
    # `pacman -S --needed --noconfirm git base-devel` acontece DE VERDADE na
    # máquina de quem estava só conferindo — e o contêiner Arch da construção
    # na nuvem roda como root. O sintoma era ela ficar vermelha dizendo que o
    # argumento se perdia; o que aconteceu foi ela ter tentado instalar
    # pacote, morrido no `USER: unbound variable` e nunca chegado ao sudo de
    # mentira. Então baixamos para o `nobody` antes de executar.
    corre=(env "PATH=$falso:$PATH" bash airootfs/usr/local/bin/stylus-app yay)
    if [[ $EUID -eq 0 ]]; then
        if command -v setpriv >/dev/null 2>&1; then
            corre=(setpriv --reuid=65534 --regid=65534 --clear-groups "${corre[@]}")
        elif command -v runuser >/dev/null 2>&1; then
            corre=(runuser -u nobody -- "${corre[@]}")
        else
            corre=()
        fi
    fi
    if [[ ${#corre[@]} -eq 0 ]]; then
        rm -rf "$falso"
        printf '  %s—%s como root e sem setpriv/runuser para baixar\n' "$y" "$z"
    else
        saida=$(timeout 20 "${corre[@]}" 2>&1)
        rm -rf "$falso"
        if grep -q 'SUDO:.* yay$' <<<"$saida"; then
            ok "o \`stylus app NOME\` chega do outro lado do sudo com o NOME"
        else
            bad "o \`stylus app yay\` perde o argumento ao pedir root"
            head -3 <<<"$saida" | sed 's/^/      /'
        fi
    fi
else
    printf '  %s—%s sem o stylus-app\n' "$y" "$z"
fi

# ── nada de gosto se aplica sem as duas trancas ───────────────────────────
# O stylus-kde-shortcuts roda a CADA login do KDE. Tudo que ele mexe em gosto
# — papel de parede, paleta, tema de widget, cursor — tem que passar por
# DUAS condições:
#
#     primeira_vez X        nunca fizemos isto nesta casa
#     ninguem_escolheu ...  e a pessoa também não escolheu nada ali
#
# A segunda é a que vale: o carimbo mora em ~/.local/state e essa pasta some
# com mais facilidade do que parece (uma casa migrada, um state limpo).
# Perdido o carimbo, um ajuste "de uma vez só" roda de novo e apaga o papel
# de parede que a pessoa escolheu — que é a coisa que mais rápido faz alguém
# trocar de distribuição, e é o defeito que estas trancas existem para
# impedir.
sec "o KDE não desfaz a escolha de ninguém"
KSH=airootfs/usr/local/bin/stylus-kde-shortcuts
if [[ -f $KSH ]]; then
    sem_tranca=$(awk '
        /^[[:space:]]*#/ { next }
        { linhas[NR] = $0 }
        /plasma-apply-(wallpaperimage|colorscheme|cursortheme)|kvantummanager/ {
            tem_pv = 0; tem_ne = 0
            for (i = NR - 12; i <= NR; i++) {
                if (linhas[i] ~ /primeira_vez/)     tem_pv = 1
                if (linhas[i] ~ /ninguem_escolheu/) tem_ne = 1
            }
            # A própria definição do comando não conta como uso.
            if ($0 ~ /command -v/ && !(tem_pv || tem_ne)) next
            if (!tem_pv || !tem_ne) print NR
        }' "$KSH" | tr '\n' ' ')
    if [[ -n ${sem_tranca// /} ]]; then
        bad "aplica gosto sem as duas trancas, nas linhas: $sem_tranca"
    else
        ok "papel de parede, paleta, cursor e widget só na primeira vez e só se ninguém escolheu"
    fi
else
    printf '  %s—%s sem o stylus-kde-shortcuts\n' "$y" "$z"
fi

# ── ninguém chama o xdg-user-dirs-update no escuro ────────────────────────
# Ele NÃO é inofensivo em cima de um user-dirs.dirs que já existe: toda
# entrada cuja pasta não estiver montada naquele instante ele reescreve como
# `XDG_MUSIC_DIR="$HOME/"`. Uma coleção num disco externo, num NFS ou no
# celular pelo WebDAV basta — e o estrago aparece longe, no dia em que o
# `xdg-user-dir DESKTOP` devolver a casa inteira e alguém escrever ali.
#
# Duas passagens já tinham nascido sem guarda (o stylus-session e o config do
# i3), com o mesmo comentário longo explicando o perigo três arquivos ao
# lado. Quem chamar tem que falar de user-dirs.dirs no mesmo arquivo.
sec "o xdg-user-dirs-update é sempre guardado"
# Linha de comentário não conta — foi assim que a conferência do python
# embutido nasceu acusando o próprio exemplo dentro do próprio comentário.
# Aqui o arquivo do i3 EXPLICA por que a chamada saiu de lá, e explicar não
# é chamar.
nus=""
while IFS= read -r f; do
    grep -vE '^[[:space:]]*#' "$f" | grep -q 'xdg-user-dirs-update' || continue
    grep -q 'user-dirs\.dirs' "$f" || nus+=" ${f#./}"
done < <(grep -rl 'xdg-user-dirs-update' airootfs 2>/dev/null)
if [[ -n $nus ]]; then
    bad "chamam o xdg-user-dirs-update sem olhar o user-dirs.dirs:$nus"
else
    ok "toda chamada ao xdg-user-dirs-update é guardada"
fi

# ── o Python escondido dentro dos scripts de shell ────────────────────────
# A conferência de sintaxe de python acima só olha arquivos .py. Metade da
# lógica de `stylus-qobuz`, `stylus-spotify` e companhia mora em heredoc:
#
#     "$PY" - "$alvo" <<'QOBUZDL'
#     ...cem linhas de python...
#     QOBUZDL
#
# Nada nunca leu esse python. Um erro de sintaxe ali passa por TODAS as
# conferências, passa pelo `bash -n` (que só vê um heredoc bem fechado), e
# só aparece na máquina de alguém, no instante em que a pessoa aperta baixar.
sec "o python que mora dentro dos scripts"
py_heredoc=$(mktemp -d)
trap 'rm -rf "$py_heredoc"' EXIT
achados=0; quebrados=""
while IFS= read -r -d '' f; do
    head -c 200 "$f" | grep -qE '^#!.*(bash|sh)\b' || continue
    # Só os heredocs entregues a um python: um <<'EOF' de `cat` não é código.
    mapfile -t marcas < <(grep -vE '^[[:space:]]*#' "$f" |
                          grep -oE '(python3?|\$PY|\$\{PY\})[^|>]*<<-?'"'"'?[A-Za-z_][A-Za-z0-9_]*' |
                          grep -oE "[A-Za-z_][A-Za-z0-9_]*$")
    for marca in "${marcas[@]}"; do
        [[ -n $marca ]] || continue
        awk -v m="$marca" '
            $0 ~ /^[ \t]*#/ && !dentro { next }
            $0 ~ ("<<'"'"'?" m "'"'"'?$") && !dentro { dentro=1; next }
            dentro && $0 == m { dentro=0; next }
            dentro { print }
        ' "$f" > "$py_heredoc/t.py"
        [[ -s $py_heredoc/t.py ]] || continue
        achados=$((achados+1))
        if ! python3 -c "import ast,io,sys;ast.parse(io.open(sys.argv[1],encoding='utf-8').read())" \
                "$py_heredoc/t.py" 2>/dev/null; then
            quebrados+=" ${f#./}:$marca"
        fi
    done
done < <(find airootfs/usr/local/bin airootfs/usr/share/stylus tools -type f -print0 2>/dev/null)
if [[ -n $quebrados ]]; then
    bad "python embutido que não compila:$quebrados"
elif (( achados )); then
    ok "os $achados blocos de python dentro de scripts compilam"
else
    bad "nenhum heredoc de python encontrado — a busca parou de achar"
fi

# ── a playlist sorteada é sorteada ANTES do corte ─────────────────────────
# **Sintoma:** com teto de 200 faixas, "as primeiras 200" de uma playlist de
# 853 são sempre as MESMAS — 653 faixas que este sistema nunca tocaria, e
# nada na tela dizendo isso. O `--sortear` só resolve se o embaralhamento
# acontecer ANTES do corte; sorteando depois, ele embaralha as mesmas 200 de
# sempre e o defeito continua inteiro, agora com uma opção que finge
# consertá-lo.
#
# A conferência roda o `uma_lista` de verdade com um cliente de mentira: sem
# rede, sem conta, sem assinatura.
sec "a playlist sorteada sai de dentro da playlist inteira"
# O stderr vai para o lixo de propósito: o qobuz_stream escreve ali as linhas
# de progresso ("playlist com 120 faixas; pegando sorteadas 10"), e elas
# entrariam na frente da resposta. O que importa sai pelo stdout, e um erro
# inesperado vira uma linha ERRO pelo `except` lá embaixo.
saida=$(python3 - <<'QOBUZEOF' 2>/dev/null
import json, os, re, shutil, sys, tempfile, traceback
sys.path.insert(0, "airootfs/usr/share/stylus")
try:
    import qobuz_stream as q
except BaseException as e:                               # noqa: BLE001
    # BaseException pelo mesmo motivo da conferência do side-watch logo
    # adiante: um módulo que responde a dependência faltando com `sys.exit`
    # levanta SystemExit, que não é Exception — e a conferência ficaria
    # VERMELHA numa máquina onde ela nem chegou a rodar.
    print("PULA %s" % e)
    raise SystemExit(0)

tmp = tempfile.mkdtemp()
q.CACHE, q.TETO = tmp, 10


class ClienteFalso:
    def get_plist_meta(self, _pid):
        yield {"name": "Grande", "owner": {"name": "Dono"},
               "tracks": {"items": [
                   {"id": i, "title": "F%03d" % i, "duration": 200,
                    "streamable": True} for i in range(120)]}}

    def get_track_url(self, tid, fmt_id=27):
        return {"url": "https://exemplo.invalid/%s.flac" % tid}


def titulos(sortear):
    lista = q.uma_lista(ClienteFalso(), 42, sortear=sortear)
    with open(os.path.join(os.path.dirname(lista), "disco.json"),
              encoding="utf-8") as fh:
        m = json.load(fh)
    return [t["title"] for t in m["tracks"]], m


def numeros(ts):
    # O título no manifesto é "quem — título" (numa playlist cada faixa é de
    # um artista), então o número sai por busca e não por fatia.
    return [int(re.search(r"F(\d+)", t).group(1)) for t in ts]


try:
    normal, m_normal = titulos(False)
    um, m_um = titulos(True)
    dois, _ = titulos(True)
    if numeros(normal) != list(range(q.TETO)):
        print("ERRO sem --sortear a lista saiu fora da ordem da playlist")
    elif not any(n >= q.TETO for n in numeros(um)):
        print("ERRO a sorteada só pegou as primeiras %d" % q.TETO)
    elif um == dois:
        print("ERRO duas rodadas sorteadas saíram iguais")
    elif not m_um.get("sorteada") or m_normal.get("sorteada"):
        print("ERRO o disco.json não marca quem foi sorteada")
    elif not isinstance(m_normal.get("assinado_em"), int):
        print("ERRO falta o assinado_em (a validade dos endereços)")
    else:
        print("OK %d de 120, e outras a cada vez" % len(um))
except Exception:                                        # noqa: BLE001
    print("ERRO %s" % traceback.format_exc().replace("\n", " | "))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
QOBUZEOF
)
case "$saida" in
    OK*)   ok "a playlist sorteada ${saida#OK }" ;;
    PULA*) printf '  %s—%s sem o qobuz_stream aqui: %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "o sorteio da playlist não sorteia a playlist inteira"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

# ── os favoritos do Qobuz vêm TODOS, não os cem primeiros ─────────────────
# **Sintoma:** a loja mostrava 100 discos e parava. Sem recado, sem "mostrando
# 100 de 340" — os outros simplesmente não existiam ali, e quem favoritou 200
# discos no celular via metade da própria estante. A chamada tinha `offset=0`
# escrito à mão e nunca uma segunda página.
#
# Um laço que fala com a rede tem que ter mais de uma saída, senão um dia ele
# não sai: a conferência põe um Qobuz de mentira e cobra as quatro (total
# alcançado, página curta, página vazia, teto).
sec "os favoritos e as listas do Qobuz vêm todos"
saida=$(python3 - <<'FAVEOF' 2>/dev/null
import importlib.machinery as _im, importlib.util as _iu, sys, types, traceback
sys.path.insert(0, "airootfs/usr/share/stylus")
# O qobuz_busca precisa do qobuz-dl instalado; aqui só interessa a paginação.
_m = types.ModuleType("qobuz_busca")
_m.Recusa = type("Recusa", (Exception,), {})
_m.cliente = lambda: None
_m.disco = lambda i: i
sys.modules["qobuz_busca"] = _m
try:
    _spec = _iu.spec_from_loader("qs", _im.SourceFileLoader(
        "qs", "airootfs/usr/share/stylus/qobuz_shelf.py"))
    qs = _iu.module_from_spec(_spec)
    _spec.loader.exec_module(qs)
except BaseException as e:                               # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)


class Cli:
    sec = "x"

    def __init__(self, total, declara=True):
        self.total, self.declara, self.chamadas = total, declara, []

    def api_call(self, _ep, **kw):
        off, lim = kw["offset"], kw["limit"]
        self.chamadas.append((off, lim))
        itens = [{"id": i} for i in range(off, min(off + lim, self.total))]
        bloco = {"items": itens}
        if self.declara:
            bloco["total"] = self.total
        return {"albums": bloco}


class Vazio(Cli):
    def api_call(self, _ep, **kw):
        return {}


try:
    erros = []
    for total, teto in ((340, 1000), (100, 1000), (7, 1000), (0, 1000),
                        (900, 250)):
        c = Cli(total)
        itens, _t = qs.favoritos_todos(c, teto)
        if len(itens) != min(total, teto):
            erros.append("total=%d teto=%d veio %d" % (total, teto, len(itens)))
    c = Cli(250, declara=False)
    if len(qs.favoritos_todos(c, 1000)[0]) != 250:
        erros.append("sem 'total' declarado, parou cedo")
    if qs.favoritos_todos(Vazio(10), 1000)[0]:
        erros.append("resposta vazia devolveu disco")

    # E as PLAYLISTS, que tinham o mesmo `limit=100` fixo escrito ao lado
    # dos favoritos. Passou despercebido porque cem playlists é muita
    # playlist — mas é o mesmo defeito.
    class CliLista:
        def __init__(self, total, aceita_offset=True):
            self.total, self.aceita_offset = total, aceita_offset

        def get_user_playlists(self, limit=100, offset=None):
            if offset is None:
                if not self.aceita_offset:
                    return {"playlists": {"items": [{"id": i}
                                                    for i in range(limit)],
                                          "total": self.total}}
                offset = 0
            elif not self.aceita_offset:
                raise TypeError("offset não existe nesta versão")
            itens = [{"id": i}
                     for i in range(offset, min(offset + limit, self.total))]
            return {"playlists": {"items": itens, "total": self.total}}

    if len(qs.listas_todas(CliLista(240), 500)[0]) != 240:
        erros.append("as playlists pararam antes das 240")
    # Sem `offset` na versão instalada, volta ao de antes em vez de estourar.
    velho = qs.listas_todas(CliLista(240, aceita_offset=False), 500)[0]
    if len(velho) != qs.POR_PAGINA:
        erros.append("sem offset, as playlists deviam voltar à 1ª página")

    if erros:
        print("ERRO %s" % "; ".join(erros))
    else:
        print("OK 340 favoritos em 4 páginas e 240 listas em 3, "
              "com o teto cortando com recado")
except BaseException:                                    # noqa: BLE001
    print("ERRO %s" % traceback.format_exc().replace("\n", " | "))
FAVEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s sem o qobuz_shelf aqui: %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "a loja do Qobuz para de contar disco cedo demais"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

# ── a assinatura vencida do Qobuz é renovada com a música tocando ─────────
# **Sintoma:** os endereços do Qobuz valem ~1 h e uma playlist de 200 faixas
# são 13. Passada a hora, o mpv pedia o endereço seguinte, levava 403, pulava
# para o próximo, e varria o resto da lista em segundos — "a música parou
# sozinha", sem nada na tela nem no journal ligando aquilo a uma assinatura.
#
# Duas coisas aqui podem quebrar em silêncio e as duas são conferidas com um
# mpv de mentira:
#
#   1. A ORDEM DA REMOÇÃO. Tirando do começo para o fim, cada remoção empurra
#      o resto e metade da cauda sobrevive misturada com a nova. Tem que ser
#      de trás para a frente.
#   2. A faixa que está TOCANDO não pode ser removida — o fluxo dela já está
#      aberto, e tirá-la é cortar o som para renovar o que vem depois.
sec "a assinatura do Qobuz é renovada sem cortar o som"
saida=$(python3 - <<'RENOVAEOF' 2>/dev/null
import importlib.util, json, os, shutil, sys, tempfile, time, traceback
sys.path.insert(0, "airootfs/usr/share/stylus/deck")
try:
    # Loader explícito: o arquivo não termina em .py (é um COMANDO), e sem
    # isso o `spec_from_file_location` devolve um spec com loader=None e a
    # conferência "pula" em vez de conferir.
    import importlib.machinery as _im
    spec = importlib.util.spec_from_loader(
        "sidewatch",
        _im.SourceFileLoader("sidewatch",
                             "airootfs/usr/local/bin/stylus-side-watch"))
    sw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sw)
except BaseException as e:                               # noqa: BLE001
    # BaseException e não Exception: o stylus-side-watch responde a um vinyl
    # ausente com `sys.exit(...)`, que levanta SystemExit — e SystemExit não
    # é Exception. Com `except Exception` a saída escapava por cima do PULA,
    # o stdout vinha vazio e a conferência ficava VERMELHA numa máquina que
    # só não tem numpy (o contêiner da construção na nuvem, por exemplo).
    print("PULA %s" % e)
    raise SystemExit(0)

tmp = tempfile.mkdtemp()


def disco(fonte="qobuz-lista", idade=99999):
    with open(os.path.join(tmp, "disco.json"), "w", encoding="utf-8") as fh:
        json.dump({"fonte": fonte, "assinado_em": int(time.time()) - idade,
                   "tracks": [{"title": "F%d" % i, "duration": 9,
                               "url": "u%d" % i, "qid": 100 + i}
                              for i in range(6)]}, fh)


class Album:
    folder = tmp


class IPCFalso:
    def __init__(self):
        self.cmds = []

    def connect(self):
        return True

    def get(self, p):
        return {"playlist-pos": 2, "playlist-count": 6}.get(p)

    def command(self, *a):
        self.cmds.append(a)
        return True

    def close(self):
        pass


class Resposta:
    returncode = 0

    def __init__(self, saida):
        self.stdout, self.stderr = saida, ""


try:
    # 1. quando renovar, e quando não
    disco(idade=99999)
    velha = sw.precisa_renovar(Album())
    disco(idade=5)
    nova = sw.precisa_renovar(Album())
    os.remove(os.path.join(tmp, "disco.json"))
    local = sw.precisa_renovar(Album())
    disco(idade=99999)

    # 2. a cirurgia na fila do mpv
    cauda = os.path.join(tmp, "cauda.m3u")
    with open(cauda, "w", encoding="utf-8") as fh:
        fh.write("#EXTM3U\n")
    falso = IPCFalso()
    sw.vinyl._MpvIPC = lambda: falso
    sw.subprocess.run = lambda *a, **k: Resposta(cauda + "\n")
    deu = sw.renovar_assinatura(tmp)
    remocoes = [c[1] for c in falso.cmds if c[0] == "playlist-remove"]
    carga = [c for c in falso.cmds if c[0] == "loadlist"]

    if not velha or nova or local:
        print("ERRO precisa_renovar erra o caso: velha=%s nova=%s local=%s"
              % (velha, nova, local))
    elif not deu:
        print("ERRO a renovação não chegou ao fim")
    elif remocoes != [5, 4, 3]:
        print("ERRO removeu na ordem errada: %s (tem que ser de trás)"
              % remocoes)
    elif 2 in remocoes:
        print("ERRO removeu a faixa que está tocando")
    elif carga != [("loadlist", cauda, "append")]:
        print("ERRO a cauda não foi pendurada com loadlist: %s" % carga)
    else:
        print("OK tira as 3 de trás para a frente e pendura a cauda")
except Exception:                                        # noqa: BLE001
    print("ERRO %s" % traceback.format_exc().replace("\n", " | "))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
RENOVAEOF
)
case "$saida" in
    OK*)   ok "renovando, ${saida#OK }" ;;
    PULA*) printf '  %s—%s sem o stylus-side-watch aqui: %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "a renovação da assinatura do Qobuz mexe errado na fila"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

printf '\n  %s%d passaram%s' "$g" "$PASS" "$z"
(( FAIL )) && printf ', %s%d falharam%s\n\n' "$r" "$FAIL" "$z" || printf '\n\n'
exit $(( FAIL > 0 ))
