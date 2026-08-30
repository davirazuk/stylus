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
          "android/app/src/main",
          # E a PRIMEIRA tela de todas, a de arranque. Ela ficou de fora até
          # aqui e estava inteira em VERDE — o fundo (0.039, 0.180, 0.137) e
          # um branco esverdeado no texto de estado. Escrito em fração de 0 a
          # 1, que é como o plymouth pede a cor, e por isso invisível para uma
          # conferência que só lê hexadecimal.
          "airootfs/usr/share/plymouth"]

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
        # E o plymouth, como "0.039, 0.180, 0.137" — fração de 0 a 1. Dois
        # formatos e dois lugares é onde a deriva se esconde: foi assim que o
        # esquema do Konsole (R,G,B decimal num heredoc) e o fundo verde da
        # tela de arranque passaram por anos.
        #
        # Só ali: as frações do renderizador do celular e do deck são o
        # MATERIAL do disco (corpo, sulco, intervalo), que a §5.5 governa em
        # números próprios — perto do preto de propósito, e não uma cor de
        # interface que devesse casar com a paleta.
        # Sem as linhas de comentário: o comentário que EXPLICA a cor velha
        # cita a cor velha, e uma conferência que acusa a própria explicação
        # do conserto é uma que se aprende a ignorar. Já aconteceu duas vezes
        # nesta família (a busca da capa e a do `side['label']`).
        codigo = "\n".join(ln for ln in txt.splitlines()
                           if not ln.lstrip().startswith("#"))
        for m in (re.finditer(r"\(\s*(\d\.\d{1,4})\s*,\s*(\d\.\d{1,4})"
                              r"\s*,\s*(\d\.\d{1,4})\s*\)", codigo)
                  if "plymouth" in str(arq) else ()):
            f = tuple(float(x) for x in m.groups())
            if any(x > 1.0 for x in f):
                continue
            r = tuple(int(round(x * 255)) for x in f)
            if "%02x%02x%02x" % r in pal.values():
                continue
            confere("%.3f, %.3f, %.3f" % f, r, arq)
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

# ── o sorteio não pode ler a coleção inteira ──────────────────────────────
# **Sintoma:** apertar [r] na estante travava a interface por segundos.
#
# O empurrãozinho da hora do dia (manhã pede faixa curta, noite pede longa —
# 15% de variação, e o comentário original diz "não é ditadura") precisa da
# duração média das faixas, e para isso abria um `Album` de CADA candidato.
# Numa coleção de 374 discos com uma dúzia de faixas cada, isso é o mutagen
# abrindo quatro mil e quinhentos arquivos — e um ffprobe por faixa que ele
# não souber ler — para aplicar um ajuste de quinze por cento.
#
# Duas coisas conferidas, e as duas sobre o RESULTADO: quantos álbuns o
# sorteio abre, e se ele continua puxando para o esquecido.
sec "o sorteio de disco é barato e continua puxando para o esquecido"
sorteio=$(python3 - <<'SORTEOF'
import collections
import os
import random
import struct
import sys
import tempfile
import shutil
import time
import wave

casa = tempfile.mkdtemp(prefix="stylus-sorteio-casa-")
os.environ["HOME"] = casa
sys.path.insert(0, "airootfs/usr/share/stylus/deck")
try:
    import vinyl                                          # noqa: E402
except BaseException as e:                                # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)

base = tempfile.mkdtemp(prefix="stylus-sorteio-")
erros = []
try:
    N = 40
    for i in range(N):
        d = os.path.join(base, "Art%03d" % i, "Disco")
        os.makedirs(d)
        for k in range(4):
            with wave.open(os.path.join(d, "%02d f.wav" % k), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(struct.pack("<h", 0) * 8000 * 60)
    cands = sorted(vinyl.shelf(root=base, min_tracks=1))
    if len(cands) != N:
        erros.append("a estante de mentira deu %d discos" % len(cands))

    # 1. quantos ÁLBUNS ele abre
    abertos = {"n": 0}
    real = vinyl.Album

    class _Conta(real):
        def __init__(self, *a, **k):
            abertos["n"] += 1
            super().__init__(*a, **k)

    vinyl.Album = _Conta
    try:
        vinyl.draw_record(cands, rng=random.Random(1))
    finally:
        vinyl.Album = real
    # O teto é escrito AQUI, e não lido do `vinyl._FINALISTAS`: uma
    # conferência que pergunta o limite ao próprio código não confere nada —
    # subir a constante para 999 passaria verde. Vinte é o que se aceita
    # abrir sem a interface parecer travada.
    TETO = 20
    if abertos["n"] > TETO:
        erros.append("o sorteio abriu %d álbuns de %d (o teto aqui é %d)"
                     % (abertos["n"], N, TETO))

    # 2. e continua puxando para o que faz mais tempo que não toca
    alvo = getattr(vinyl, "PLAYS", None)
    if alvo:
        os.makedirs(os.path.dirname(alvo), exist_ok=True)
        with open(alvo, "w", encoding="utf-8") as fh:
            for c in cands[:10]:
                fh.write("%d\tA\tB\t%s\n" % (int(time.time()), c))
        recentes = set(cands[:10])
        rng = random.Random(3)
        conta = collections.Counter()
        for _ in range(300):
            conta["recente" if vinyl.draw_record(cands, rng=rng) in recentes
                  else "esquecido"] += 1
        # Uniforme daria 25% de recentes; o peso quadrático tem que derrubar
        # isso para quase zero.
        if conta["recente"] > 15:
            erros.append("o esquecimento parou de pesar: %d de 300 sorteios "
                         "caíram num disco ouvido hoje" % conta["recente"])
finally:
    shutil.rmtree(base, ignore_errors=True)
    shutil.rmtree(casa, ignore_errors=True)
for e in erros:
    print(e)
SORTEOF
)
case "$sorteio" in
    "")    ok "abre no máximo uma dúzia de discos, e o esquecido ganha" ;;
    PULA*) printf '  %s—%s sem o vinyl aqui: %s\n' "$y" "$z" "${sorteio#PULA }" ;;
    *)     bad "o sorteio de disco:"
           printf '%s\n' "$sorteio" | sed 's/^/      /' ;;
esac

# ── "1 faixas" ────────────────────────────────────────────────────────────
# **Sintoma:** "1 faixas", "1 discos", "posto há 1 meses", "1 discos · 1
# vezes". Não derruba nada, não aparece em teste nenhum e não some sozinho —
# só faz o sistema parecer traduzido por máquina, e o texto que a pessoa vê
# é a única parte dele que ela lê inteira.
#
# A regra do plural estava escrita à mão em quinze lugares (`f"{n} faixas"`),
# que é a mesma doença das cores e das listas de extensão: basta uma cópia
# esquecer o caso do 1. Agora sai do `model.plural`, e a conferência é sobre
# o RESULTADO — pede a frase com n=1 e n=2 e olha o que volta.
sec "o plural não mente quando é um só"
plur=$(python3 - <<'PLUREOF'
import sys
import time

sys.path.insert(0, "airootfs/usr/share/stylus/deck")
sys.path.insert(0, "airootfs/usr/share/stylus/ui")
try:
    import model
except Exception as e:                                   # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)

erros = []
casos = [
    (1, "disco", None, "1 disco"),
    (2, "disco", None, "2 discos"),
    (0, "disco", None, "0 discos"),
    (1, "faixa", None, "1 faixa"),
    (1, "vez", "vezes", "1 vez"),
    (3, "vez", "vezes", "3 vezes"),
    (1, "mês", "meses", "1 mês"),
]
for n, um, muitos, esperado in casos:
    got = model.plural(n, um, muitos) if muitos else model.plural(n, um)
    if got != esperado:
        erros.append("plural(%d, %r) = %r, esperado %r" % (n, um, got, esperado))

# E o `ha_quanto`, que tinha o mesmo defeito em três das cinco frases.
agora = time.time()
for dias, esperado in ((0.5, "posto hoje"), (1.5, "posto ontem"),
                       (3, "posto há 3 dias"), (35, "posto há 1 mês"),
                       (70, "posto há 2 meses"), (400, "posto há 1 ano"),
                       (800, "posto há 2 anos")):
    got = model.ha_quanto(agora - dias * 86400)
    if got != esperado:
        erros.append("ha_quanto(%s dias) = %r, esperado %r"
                     % (dias, got, esperado))
if model.ha_quanto(0) != "nunca posto":
    erros.append("ha_quanto(0) = %r" % model.ha_quanto(0))

# Ninguém pode voltar a escrever a regra à mão nas telas.
import pathlib
import re

for arq in (pathlib.Path("airootfs/usr/share/stylus/ui/app.py"),):
    for n_l, linha in enumerate(arq.read_text(encoding="utf-8").splitlines(), 1):
        nu = linha.split("#", 1)[0]
        if re.search(r'\{[^{}]*\}\s*(faixas|discos|vezes)\b', nu):
            erros.append("%s:%d escreve o plural à mão: %s"
                         % (arq.name, n_l, linha.strip()[:60]))
for e in erros:
    print(e)
PLUREOF
)
case "$plur" in
    "")    ok "\"1 disco\", \"2 discos\", \"posto há 1 mês\" — o caso do 1 existe" ;;
    PULA*) printf '  %s—%s sem o model aqui: %s\n' "$y" "$z" "${plur#PULA }" ;;
    *)     bad "o plural mente:"
           printf '%s\n' "$plur" | sed 's/^/      /' ;;
esac

# ── o celular reparte o disco como o computador ───────────────────────────
# **Sintoma:** o MESMO disco saía com lados diferentes nos dois lados do
# sistema, e o "vira em X" dizia coisas diferentes. O celular tinha uma regra
# própria — teto de 22 minutos (aqui são 26) e enchia cada lado até a boca —
# que ainda por cima podia dar um número ÍMPAR de lados, que é um objeto que
# não existe.
#
# A coleção é a mesma dos dois lados, e a promessa do sistema é que ela SE
# PARECE a mesma. Agora o `buildSides` do VinylActivity.kt é a transliteração
# do `Album._build_sides`, conferida contra ele em 192 formas de disco antes
# de entrar.
#
# ATENÇÃO: nada neste repositório COMPILA o app do celular — não há gradle no
# check.sh nem na construção da nuvem. O que dá para conferir daqui é que os
# NÚMEROS e as peças da lei continuam os mesmos; a sintaxe não.
sec "o celular reparte o disco como o computador"
cel=$(python3 - <<'CELEOF'
import pathlib
import re
import sys

# A regra dos lados mora no Lados.kt desde que o aviso de virar o disco
# passou a existir no celular; o VinylActivity.kt só a usa.
kt = pathlib.Path("android/app/src/main/kotlin/io/stylus/player/Lados.kt")
if not kt.is_file():
    raise SystemExit(0)
fonte = kt.read_text(encoding="utf-8")

sys.path.insert(0, "airootfs/usr/share/stylus/deck")
try:
    import vinyl                                          # noqa: E402
except BaseException as e:                                # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)

# O teto, em minutos, dos dois lados.
m = re.search(r"SIDE_MAX_MS\s*=\s*(\d+)L?\s*\*\s*60L?\s*\*\s*1000L", fonte)
if m is None:
    print("não achei o teto do lado no VinylActivity.kt")
else:
    daqui = int(vinyl.SIDE_MAX_SECONDS // 60)
    de_la = int(m.group(1))
    if de_la != daqui:
        print("o teto do lado é %d min no celular e %d min aqui"
              % (de_la, daqui))

# As duas peças da lei que o celular não tinha.
if "nSides = " not in fonte or "2 *" not in fonte:
    print("o celular não arredonda o número de DISCOS (lados em par)")
if "sides.size % 2 == 1" not in fonte:
    print("o celular não refaz o corte quando dá um número ímpar de lados")
if "total - curStart" not in fonte:
    print("o alvo do equilíbrio no celular não vem do que RESTA")
CELEOF
)
case "$cel" in
    "")    ok "o teto do lado e a lei do corte são os mesmos nos dois lados" ;;
    PULA*) printf '  %s—%s sem o vinyl aqui: %s\n' "$y" "$z" "${cel#PULA }" ;;
    *)     bad "o celular reparte o disco de outro jeito:"
           printf '%s\n' "$cel" | sed 's/^/      /' ;;
esac

# ── o aviso do fim do lado pede o GESTO certo ─────────────────────────────
# **Sintoma:** num disco DUPLO o aviso mandava a coisa errada em dois dos
# três casos.
#
# A decisão morava dentro do laço e perguntava "este é o último lado?":
#
#     ultimo = i >= len(al.sides) - 1
#     if ultimo and i == len(al.sides) - 1:      ← a mesma coisa duas vezes
#         "vire o disco para o LADO X"
#     else:
#         "agora o LADO X"
#
# Num LP de dois lados isso acerta por acidente. Num duplo: A→B dizia "agora
# o LADO B" (e ali se vira o disco), B→C dizia "agora o LADO C" (e ali se
# TROCA de disco, que é outro gesto e outro objeto), e só C→D acertava.
#
# A pergunta certa é "que gesto o objeto pede agora?", e o objeto responde
# pelo índice: lado ÍMPAR é o verso do que já está no prato — vire; lado PAR
# é o começo de outro disco — troque. Isto é a tese do sistema inteiro, e
# estava errado justamente no disco que mais precisa dela.
sec "o aviso do fim do lado pede o gesto certo"
gesto=$(python3 - <<'GESTOEOF'
import importlib.machinery as _im
import importlib.util as _iu
import sys

sys.path.insert(0, "airootfs/usr/share/stylus/deck")
spec = _iu.spec_from_loader("sw", _im.SourceFileLoader(
    "sw", "airootfs/usr/local/bin/stylus-side-watch"))
mod = _iu.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except BaseException as e:                               # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)


# Um Album DE VERDADE (sem __init__, que iria ao disco): a frase do gesto
# mora no vinyl.Album, e um objeto de mentira sem esse método faria o
# `recado` cair na reserva dele — o teste passaria por cima justamente do
# caminho que interessa.
import vinyl as _v


def _Alb(n, discos):
    a = _v.Album.__new__(_v.Album)
    a.name = "Disco"
    a.sides = [{"label": "SIDE " + chr(65 + i)} for i in range(n)]
    a.discos = discos
    return a


# (lados, discos, índice de destino, o que TEM que aparecer no corpo)
casos = [
    (2, 1, 1, "vire o disco"),
    (4, 2, 1, "vire o disco"),          # A→B: virar o disco 1
    (4, 2, 2, "DISCO 2"),               # B→C: trocar de disco
    (4, 2, 3, "vire o disco"),          # C→D: virar o disco 2
    (6, 3, 4, "DISCO 3"),
    (6, 3, 5, "vire o disco"),
]
for n, discos, para, esperado in casos:
    al = _Alb(n, discos)
    titulo, corpo = mod.recado(al, para - 1, para)
    if esperado not in corpo:
        print("%d lados, %s → %s: %r não tem %r"
              % (n, al.sides[para - 1]["label"], al.sides[para]["label"],
                 corpo, esperado))
    esperado_t = al.sides[para - 1]["label"].replace("SIDE", "LADO") + " acabou"
    if titulo != esperado_t:
        print("título %r, esperado %r" % (titulo, esperado_t))

# E não pode estourar com um álbum sem lados nenhum.
try:
    mod.recado(_Alb(0, 1), 0, 1)
except Exception as e:                                   # noqa: BLE001
    print("um álbum sem lados derruba o aviso: %r" % e)
GESTOEOF
)
case "$gesto" in
    "")    ok "vira o disco no lado ímpar, troca de disco no par" ;;
    PULA*) printf '  %s—%s sem o stylus-side-watch aqui: %s\n' \
                  "$y" "$z" "${gesto#PULA }" ;;
    *)     bad "o aviso do fim do lado manda a coisa errada:"
           printf '%s\n' "$gesto" | sed 's/^/      /' ;;
esac

# ── unidade de usuário que ninguém liga ───────────────────────────────────
# **Sintoma:** o scrobbler do last.fm e o botão do fone não existiam. Não
# "não funcionavam": não SUBIAM. As duas unidades estavam escritas em
# `~/.config/systemd/user/` com `WantedBy=graphical-session.target`, e um
# `WantedBy` só vale depois de um `systemctl --user enable` — que nada neste
# repositório jamais chamou.
#
# E o lugar estava errado de qualquer jeito: o `sync.sh` PRESERVA o
# ~/.config (é a regra, e é boa), então unidade nova nunca alcança quem já
# instalou. O que precisa alcançar máquina existente vai para o
# /usr/local/bin — no caso, para o `stylus-fundo`, que já sobe os vigias nas
# duas áreas de trabalho e é seguro rodar duas vezes.
sec "nenhuma unidade de usuário escrita e nunca ligada"
unidades=$(python3 - <<'UNIEOF'
import os
import pathlib
import re

raiz = pathlib.Path("airootfs/etc/skel/.config/systemd/user")
if not raiz.is_dir():
    raise SystemExit(0)

# Todo o repositório, para procurar quem liga.
texto = []
for r, ds, fs in os.walk("."):
    ds[:] = [d for d in ds if d not in (".git", "__pycache__", "work", "out")]
    for f in fs:
        try:
            texto.append(open(os.path.join(r, f), encoding="utf-8",
                              errors="ignore").read())
        except OSError:
            pass
todo = "\n".join(texto)

for u in sorted(raiz.glob("*.service")):
    corpo = u.read_text(encoding="utf-8")
    if "[Install]" not in corpo:
        continue           # unidade só para ser chamada por outra: tudo bem
    nome = u.stem
    # Alguém dá `systemctl --user enable` nela? Ou existe um `.wants`?
    liga = re.search(r"--user\s+enable[^\n]*%s" % re.escape(nome), todo)
    wants = list(raiz.glob("*.wants/%s" % u.name))
    if not liga and not wants:
        print("%s: tem [Install] e ninguém a liga "
              "(e o sync.sh preserva o ~/.config, então ela nem chega)"
              % u.name)
UNIEOF
)
if [[ -z $unidades ]]; then
    ok "toda unidade de usuário do /etc/skel é ligada por alguém"
else
    bad "unidade de usuário escrita e nunca ligada:"
    printf '%s\n' "$unidades" | sed 's/^/      /'
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
    print("PULA o album.py saiu ao ser carregado")
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
case "$barra" in
    "")    ok "o disco da rede chega ao módulo da barra, e o lado usa .get" ;;
    PULA*) printf '  %s—%s %s\n' "$y" "$z" "${barra#PULA }" ;;
    *)     bad "o módulo do disco na barra:"
           printf '%s\n' "$barra" | sed 's/^/      /' ;;
esac

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

# Guardado: o mutagen é dependência do sistema instalado, não deste
# contêiner. Sem ele a conferência não tem como rodar — e um traceback aqui
# se leria como "o extrator de capas quebrou", que é o contrário da verdade.
try:
    import mutagen
    from mutagen.flac import FLAC, Picture
    from mutagen.mp4 import MP4Cover
    import extract_covers as EC
except BaseException as e:                               # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)

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
case "$capas" in
    "")    ok "capa achada em FLAC, MP4/ALAC e Ogg/Opus (e nenhuma inventada)" ;;
    PULA*) printf '  %s—%s sem o mutagen aqui: %s\n' "$y" "$z" "${capas#PULA }" ;;
    *)     bad "o extrator de capas não lê todo formato:"
           printf '%s\n' "$capas" | sed 's/^/      /' ;;
esac

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

sec "as duas metades da coleção, faixa por faixa"
# **Sintoma:** de duas faixas chamadas "01 - Intro.flac", em álbuns
# diferentes e nenhuma das duas no celular, só UMA era mandada. A outra não
# aparecia em lista nenhuma e o `status` dizia que estava tudo sincronizado —
# e "Intro", "Untitled" e "track01" repetem em dezenas de discos.
saida=$(python3 - <<'PLANOEOF' 2>&1
import importlib.machinery as im, importlib.util, traceback
spec = importlib.util.spec_from_loader(
    "sp", im.SourceFileLoader("sp", "airootfs/usr/local/bin/stylus-phone"))
sp = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(sp)
except BaseException as e:                               # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)
try:
    # 1. o mesmo NOME em álbuns diferentes, nada do outro lado: vão os dois
    mandar, _t, _i = sp.plan({"A/01 - Intro.flac": 10, "B/01 - Intro.flac": 20,
                              "A/02 - Outra.flac": 30}, {})
    nomes = sorted(f for f, _s in mandar)
    # 2. o mesmo arquivo em dois formatos na MESMA pasta: só o melhor
    m2, _t, _i = sp.plan({"A/01 - Intro.flac": 5000, "A/01 - Intro.mp3": 500}, {})
    # 3. do lado de lá vale a mesma coisa
    _m, t3, _i = sp.plan({}, {"Intro.flac": 10, "p/Intro.flac": 20})
    if len(nomes) != 3:
        print("ERRO só %d de 3 seriam mandadas: %s" % (len(nomes), nomes))
    elif [f for f, _s in m2] != ["A/01 - Intro.flac"]:
        print("ERRO manda o mp3 junto do flac: %s" % [f for f, _s in m2])
    elif len(t3) != 2:
        print("ERRO só %d de 2 seriam trazidas" % len(t3))
    else:
        print("OK nome repetido em álbuns diferentes vai inteiro, formato pior fica")
except Exception:                                        # noqa: BLE001
    print("ERRO %s" % traceback.format_exc().replace("\n", " | "))
PLANOEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s sem o stylus-phone aqui: %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "o plano de sincronia do celular perde faixa"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "o que tocou no celular entra no registro"
# **Sintoma:** o `stylus phone scrobbles` dizia "memória da coleção
# atualizada" e não atualizava nada. O agente do Termux escreve a quarta
# coluna (a PASTA) vazia de propósito — "o PC resolve" — e essa resolução
# nunca foi escrita: as linhas iam para o plays.tsv com pasta vazia, que não
# é disco nenhum, e com o carimbo de AGORA em vez do carimbo do celular.
saida=$(python3 - <<'SCROBEOF' 2>&1
import importlib.machinery as im, importlib.util, os, shutil, sys, tempfile
import traceback, types
tmp = tempfile.mkdtemp()
plays = os.path.join(tmp, "plays.tsv")
fake = types.ModuleType("vinyl")
fake.AUDIO_EXT = (".flac", ".mp3")
fake.PLAYS_TSV = plays
fake.library_root = lambda: tmp
CAT = {("radiohead", "kid a"): os.path.join(tmp, "Radiohead", "Kid A")}
fake.resolve_album = lambda path=None, artist="", album="": \
    CAT.get((artist.lower(), album.lower()))


def _play_rows():
    try:
        with open(plays, encoding="utf-8") as fh:
            for ln in fh:
                p = ln.rstrip("\n").split("\t")
                if len(p) >= 4:
                    yield float(p[0]), p[3]
    except OSError:
        return


fake._play_rows = _play_rows
sys.modules["vinyl"] = fake
spec = importlib.util.spec_from_loader(
    "sp", im.SourceFileLoader("sp", "airootfs/usr/local/bin/stylus-phone"))
sp = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(sp)
except BaseException as e:                               # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)
try:
    T0 = 1700000000
    linhas = [(T0 + i * 240, "Radiohead", "Kid A") for i in range(12)]
    linhas += [(T0 + 10800 + i * 240, "Radiohead", "Kid A") for i in range(4)]
    linhas += [(T0 + i * 300, "Alguém", "Disco que não tenho") for i in range(3)]
    tsv = os.path.join(tmp, "phone.tsv")
    with open(tsv, "w", encoding="utf-8") as fh:
        for ts, a, al in linhas:
            fh.write("%d\t%s\t%s\t\n" % (ts, a, al))   # a PASTA vem vazia
    novas, _rep, sem, _ex = sp.importar_scrobbles(tsv)
    de_novo = sp.importar_scrobbles(tsv)[0]
    escritas = [ln.rstrip("\n").split("\t")
                for ln in open(plays, encoding="utf-8")]
    if novas != 2:
        print("ERRO 12 faixas de um álbum + 4 três horas depois deram %d "
              "colocações (tem que dar 2)" % novas)
    elif de_novo:
        print("ERRO importar duas vezes anotou %d vez(es) de novo" % de_novo)
    elif any(not l[3].strip() for l in escritas):
        print("ERRO linha escrita sem pasta: %s" % escritas)
    elif any(abs(int(l[0]) - T0) > 20000 for l in escritas):
        print("ERRO o carimbo é o de agora, não o do celular: %s"
              % [l[0] for l in escritas])
    elif sem != 3:
        print("ERRO %d linhas sem disco (eram 3)" % sem)
    else:
        print("OK 12 faixas viram uma colocação, com a data do celular, e "
              "reimportar não dobra")
except Exception:                                        # noqa: BLE001
    print("ERRO %s" % traceback.format_exc().replace("\n", " | "))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
SCROBEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s sem o stylus-phone aqui: %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "o que tocou no celular não chega à memória da coleção"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "montar o celular de novo não apaga a senha"
# **Sintoma:** com o `stylus webdav sozinho` ligado e um servidor que pede
# senha, o celular montava uma vez e nunca mais. O serviço roda sem terminal:
# o `read` da senha volta vazio na hora e o `rclone config create` reescrevia
# o remoto SEM a senha guardada. Esta conferência RODA o comando com um
# rclone de mentira e olha se ele o reescreveu.
tmpw=$(mktemp -d)
mkdir -p "$tmpw/bin" "$tmpw/casa"
cat > "$tmpw/bin/rclone" <<'RCEOF'
#!/usr/bin/env bash
case "${1:-}" in
    listremotes) echo "stylus-celular:" ;;
    config) echo "$*" >> "$FALSO/chamadas" ;;
    mount)  mkdir -p "$3"; touch "$FALSO/montou" ;;
    obscure) echo "xxx" ;;
esac
exit 0
RCEOF
cat > "$tmpw/bin/mountpoint" <<'MPEOF'
#!/usr/bin/env bash
[[ -f $FALSO/montou ]]
MPEOF
printf '#!/usr/bin/env bash\nexit 0\n' > "$tmpw/bin/fusermount3"
chmod +x "$tmpw/bin"/*
printf 'URL=http://192.168.0.10:8080/\nUSUARIO=eu\n' \
    > "$tmpw/casa/.config-stylus-webdav"
mkdir -p "$tmpw/casa/.config/stylus"
cp "$tmpw/casa/.config-stylus-webdav" "$tmpw/casa/.config/stylus/webdav"
saida=$(env -i PATH="$tmpw/bin:/usr/bin:/bin" HOME="$tmpw/casa" \
        FALSO="$tmpw" STYLUS_WEBDAV_MOUNT="$tmpw/casa/celular" \
        bash airootfs/usr/local/bin/stylus-webdav ligar </dev/null 2>&1)
chamadas=$(cat "$tmpw/chamadas" 2>/dev/null || true)
if [[ -n $chamadas ]]; then
    bad "reescreveu o remoto do rclone sem terminal (apaga a senha): $chamadas"
elif [[ ! -f $tmpw/montou ]]; then
    bad "não montou nem reescreveu nada"
    printf '%s\n' "$saida" | sed 's/^/      /'
elif ! grep -qxF "$tmpw/casa/celular" "$tmpw/casa/.config/stylus/library" 2>/dev/null; then
    bad "montou e não pôs o celular na estante (~/.config/stylus/library)"
else
    ok "o mesmo endereço remonta sem tocar na senha, e entra na estante"
fi
rm -rf "$tmpw"

sec "a capa, escolhida do mesmo jeito em todo lugar"
# **Sintoma:** coleção passada por um Windows guarda `Folder.jpg` e
# `Cover.jpg` com maiúscula. O deck comparava o nome EXATO e ficava sem capa
# nenhuma; a estante caía no "primeira imagem em ordem alfabética", que numa
# pasta dessas é `AlbumArtSmall.jpg` ou `Back.jpg`. Eram QUATRO listas de
# nome de capa no sistema, e discordavam entre si.
saida=$(python3 - <<'CAPAEOF' 2>&1
import os, shutil, sys, tempfile, traceback
sys.path.insert(0, "airootfs/usr/share/stylus/deck")
try:
    import vinyl
except Exception as e:                                   # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)
tmp = tempfile.mkdtemp()


def pasta(nome, arquivos):
    d = os.path.join(tmp, nome)
    os.makedirs(d, exist_ok=True)
    for a in arquivos:
        open(os.path.join(d, a), "w").close()
    return d


try:
    casos = [
        # (o que tem na pasta, o que tem que sair)
        (["cover.jpg", "back.jpg"], "cover.jpg"),
        (["Folder.jpg", "AlbumArtSmall.jpg"], "Folder.jpg"),   # Windows
        (["Cover.JPG"], "Cover.JPG"),
        (["folder.png"], "folder.png"),
        (["cover.jpeg"], "cover.jpeg"),
        (["front.jpg", "cover.jpg"], "cover.jpg"),             # ordem importa
        (["scan01.jpg"], "scan01.jpg"),                        # palpite do fim
        (["back.jpg"], None),                                  # só contracapa
        (["disc.png", "inlay.jpg"], None),
        ([], None),
        (["faixa.flac"], None),
    ]
    erros = []
    for i, (arquivos, esperado) in enumerate(casos):
        d = pasta("c%d" % i, arquivos)
        got = vinyl.find_cover(d)
        got = os.path.basename(got) if got else None
        if got != esperado:
            erros.append("%s -> %s (esperado %s)" % (arquivos, got, esperado))
    # a lista pronta e o os.listdir têm que dar a mesma resposta
    d = pasta("c0", [])
    if vinyl.find_cover(d, os.listdir(d)) != vinyl.find_cover(d):
        erros.append("com entries pronto responde diferente")
    if erros:
        print("ERRO " + " | ".join(erros))
    else:
        print("OK %d casos, com maiúscula do Windows e sem pôr a contracapa"
              % len(casos))
except Exception:                                        # noqa: BLE001
    print("ERRO %s" % traceback.format_exc().replace("\n", " | "))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
CAPAEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s sem o vinyl aqui: %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "a capa é escolhida errado"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

# E a quinta cópia da lista não pode nascer. Quem precisa da capa chama o
# vinyl.find_cover (ou o _raiz.find_cover, que é a ponte para as ferramentas).
# Só linhas de CÓDIGO: a conferência anterior desta família casava com o
# próprio comentário que explicava o defeito, e ficava vermelha para sempre.
fora=$(python3 - <<'FORAEOF'
import os
alvo = ("folder.jpg", "front.jpg", "folder.png")
for base, _d, fs in os.walk("airootfs"):
    for nome in fs:
        if not (nome.endswith(".py") or nome.startswith("stylus-")):
            continue
        cam = os.path.join(base, nome)
        if cam.endswith(("deck/vinyl.py", "tools/_raiz.py")) or "test_" in nome:
            continue
        try:
            with open(cam, encoding="utf-8", errors="replace") as fh:
                linhas = fh.read().splitlines()
        except OSError:
            continue
        for ln in linhas:
            nu = ln.split("#")[0] if not ln.lstrip().startswith("#") else ""
            if any(a in nu for a in alvo):
                print(cam)
                break
FORAEOF
)
if [[ -z $fora ]]; then
    ok "nenhuma segunda lista de nome de capa escrita à mão"
else
    bad "lista de nome de capa fora do vinyl/_raiz (use find_cover):"
    printf '      %s\n' $fora
fi

sec "o caminho do sinal enxerga o tocador do sistema"
# **Sintoma:** `stylus audio` respondia "nada tocando de um arquivo local
# agora — ponha um disco e rode de novo" para quem tinha ACABADO de pôr um.
# A pergunta central do comando (qual arquivo está tocando, para comparar a
# taxa dele com a do grafo) era a única que não passava pelo socket do mpv:
# ia por MPRIS, que só enxerga o mpv quando o plugin mpv-mpris está
# carregado. É o mesmo defeito que o módulo do disco da barra teve.
saida=$(python3 - <<'AUDIOEOF' 2>&1
import importlib.machinery as im, importlib.util, os, sys, tempfile, traceback
import types
tmp = tempfile.mkdtemp()
faixa = os.path.join(tmp, "01 faixa.flac")
open(faixa, "w").close()

chamou = []


class IPC:
    def connect(self):
        return True

    def get(self, prop):
        chamou.append(prop)
        return faixa if prop == "path" else None

    def close(self):
        pass


fake = types.ModuleType("vinyl")
fake.AUDIO_EXT = (".flac",)
fake._MpvIPC = IPC
sys.modules["vinyl"] = fake
spec = importlib.util.spec_from_loader(
    "sa", im.SourceFileLoader("sa", "airootfs/usr/local/bin/stylus-audio"))
sa = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(sa)
except BaseException as e:                               # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)
try:
    # Nenhum processo externo: se ele cair no playerctl, aparece aqui.
    rodou = []
    sa.run = lambda cmd, timeout=6: rodou.append(cmd) or ""
    achou = sa._caminho_tocando()
    if achou != faixa:
        print("ERRO não achou pelo socket: %r" % achou)
    elif rodou:
        print("ERRO ainda perguntou ao %s" % rodou[0][0])
    elif "path" not in chamou:
        print("ERRO não perguntou `path` ao mpv")
    else:
        # E sem mpv o playerctl continua sendo a reserva.
        fake._MpvIPC = lambda: types.SimpleNamespace(
            connect=lambda: False, get=lambda p: None, close=lambda: None)
        sa.run = lambda cmd, timeout=6: "file://" + faixa
        if sa._caminho_tocando() != faixa:
            print("ERRO sem mpv, o MPRIS deixou de ser a reserva")
        else:
            print("OK pelo socket do mpv, com o playerctl de reserva")
except Exception:                                        # noqa: BLE001
    print("ERRO %s" % traceback.format_exc().replace("\n", " | "))
AUDIOEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s sem o stylus-audio aqui: %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "o \`stylus audio\` não vê o que o sistema está tocando"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "a configuração do STYLUS mora num lugar só"
# ~/.config/stylus, escrito assim. NÃO pelo XDG_CONFIG_HOME.
#
# Não é preferência: é que quem ESCREVE não o segue. O vinyl (a estante), o
# stylus-mode, o stylus-wallpaper e o stylus-scrobble usam `~/.config`
# literal; cinco leitores usavam a variável. Numa máquina que a define — e há
# quem defina — o `stylus webdav` escrevia a estante num arquivo que ninguém
# lê, o guarda do stylus-fundo não achava o scrobble.json e o scrobbler nunca
# subia, e o stylus-kde-shortcuts não via o papel de parede escolhido e o
# trocava por cima. É a mesma família das duas árvores da polybar: dois
# lugares para a mesma coisa, e a metade que não é lida some em silêncio.
achados=$(python3 - <<'XDGEOF'
import os
import re
# A LINHA tem que falar das duas coisas: da variável e de uma pasta "stylus".
# Casar pelo caminho do arquivo acusava o `first-run.sh` por causa do
# user-dirs.dirs, que é arquivo do XDG e não nosso — e uma conferência que
# reclama do que está certo é uma que se aprende a ignorar.
alvo = re.compile(r"XDG_CONFIG_HOME")
nosso = re.compile(r'["/]stylus["/]|"stylus"|, *"stylus"')
for base in ("airootfs/usr/local/bin", "airootfs/usr/share/stylus"):
    for d, _s, fs in os.walk(base):
        if "__pycache__" in d:
            continue
        for nome in fs:
            cam = os.path.join(d, nome)
            try:
                with open(cam, encoding="utf-8", errors="replace") as fh:
                    linhas = fh.read().splitlines()
            except OSError:
                continue
            for n, ln in enumerate(linhas, 1):
                if ln.lstrip().startswith("#"):
                    continue
                if alvo.search(ln) and nosso.search(ln):
                    print("%s:%d:%s" % (cam, n, ln.strip()[:90]))
XDGEOF
)
if [[ -z $achados ]]; then
    ok "nenhum caminho de configuração do STYLUS montado com XDG_CONFIG_HOME"
else
    bad "configuração do STYLUS por XDG_CONFIG_HOME (use \$HOME/.config/stylus):"
    printf '%s\n' "$achados" | sed 's/^/      /'
fi

sec "estado escrito e nunca lido"
# A irmã da conferência de função órfã, e pela mesma razão: um campo com nome
# de recurso, escrito e nunca lido, LÊ como recurso que existe. O `Deck`
# guardava `side_index`, `pending_side` e `message` — que parecem o
# encanamento do aviso de virar o lado, a tese do projeto — e nenhum dos três
# era lido por linha nenhuma do sistema. É a família do `set_text` que
# ninguém chamava no deck e do `Nx` do diário: quando a peça está lá e o fio
# não, ler o arquivo não denuncia nada.
#
# Só `self.X = …`. Atribuir a atributo de OUTRO objeto (um pygame.Rect, um
# módulo grampeado no teste) tem efeito e não é estado morto.
saida=$(python3 - <<'MORTOEOF'
import ast
import collections
import os
lidos, escritos = set(), collections.defaultdict(list)
alvos = []
for d, _s, fs in os.walk("airootfs"):
    if "__pycache__" in d or "/venv" in d:
        continue
    for n in fs:
        if n.endswith(".py") or (n.startswith("stylus") and "." not in n):
            alvos.append(os.path.join(d, n))
for cam in alvos:
    try:
        with open(cam, encoding="utf-8") as fh:
            arv = ast.parse(fh.read())
    except (OSError, SyntaxError):
        continue
    for no in ast.walk(arv):
        if isinstance(no, ast.Attribute):
            eh_self = isinstance(no.value, ast.Name) and no.value.id == "self"
            if isinstance(no.ctx, ast.Store):
                if eh_self:
                    escritos[no.attr].append("%s:%d" % (cam, no.lineno))
            else:
                lidos.add(no.attr)
        elif isinstance(no, ast.Constant) and isinstance(no.value, str):
            # getattr("nome") e afins: uma string com o nome do campo conta
            # como leitura, senão a conferência acusa o que é lido por reflexo.
            lidos.add(no.value)
for k in sorted(escritos):
    if k not in lidos:
        print("self.%s  (%s)" % (k, ", ".join(escritos[k][:3])))
MORTOEOF
)
if [[ -z $saida ]]; then
    ok "nenhum campo de objeto escrito e nunca lido"
else
    bad "estado morto (escrito, nunca lido em lugar nenhum):"
    printf '%s\n' "$saida" | sed 's/^/      /'
fi

sec "todo atalho NOSSO está no Mod+F1"
# A conferência acima confere as teclas de foco/mover, que foi onde a ajuda
# mentiu uma vez. Esta olha o outro lado do mesmo buraco: um atalho ligado no
# i3 a um comando DO STYLUS e que não está escrito em lugar nenhum.
#
# **Sintoma:** o `Mod+Shift+O` sorteia um disco puxando para o que faz mais
# tempo que não toca — a coisa de que este sistema mais se orgulha — e não
# aparecia na lista de atalhos. Nem o `Mod+O` (o deck) nem o `Mod+/` (a
# letra). Três teclas prontas, testadas, e ninguém tinha como descobri-las
# sem ler o config do i3.
#
# Só os NOSSOS comandos: as teclas do próprio i3 (kill, layout, resize) são
# documentadas em prosa e por faixa, e exigi-las uma a uma encheria a lista
# de ruído.
CFG=airootfs/etc/skel/.config/i3/config
AJUDA=airootfs/usr/share/stylus/keybindings.txt
if [[ -f $CFG && -f $AJUDA ]]; then
    faltando=$(python3 - <<'ATALHOEOF'
import re
cfg = open("airootfs/etc/skel/.config/i3/config", encoding="utf-8").read()
ajuda = open("airootfs/usr/share/stylus/keybindings.txt", encoding="utf-8").read()
mapa = {"semicolon": ";", "slash": "/", "comma": ",", "period": ".",
        "Return": "Enter", "space": "Espaço"}
alvo = re.compile(r"\bstylus(-[a-z]+)?\b")
for m in re.finditer(r"^bindsym\s+(\$mod\S*)\s+(.*)$", cfg, re.M):
    tecla, acao = m.group(1), m.group(2)
    if not alvo.search(acao):
        continue
    partes = tecla.replace("$mod", "Mod").split("+")
    fim = partes[-1]
    fim = mapa.get(fim, fim.upper() if len(fim) == 1 else fim)
    nome = "+".join(p.replace("Control", "Ctrl") for p in partes[:-1] + [fim])
    if nome.lower() not in ajuda.lower():
        print("%s → %s" % (nome, acao.replace("exec --no-startup-id ", "")[:52]))
ATALHOEOF
)
    if [[ -z $faltando ]]; then
        ok "todo atalho do i3 que roda um comando do STYLUS está na lista"
    else
        bad "atalho ligado no i3 e ausente do Mod+F1:"
        printf '%s\n' "$faltando" | sed 's/^/      /'
    fi
else
    printf '  %s—%s sem config do i3 ou sem keybindings.txt\n' "$y" "$z"
fi

sec "a mesma tecla faz a mesma coisa nos dois modos"
# O stylus-kde-shortcuts já dizia o porquê na linha do Meta+G — "quem aprende
# o atalho num modo não o perde no outro" — e quebrava a própria regra em
# quatro das sete: Meta+D abria o toca-discos no KDE e o menu de programas no
# i3; Meta+Escape era o modo música num e o btop no outro. A mão aprende e
# erra, e ninguém desconfia da tecla: desconfia do programa.
saida=$(python3 - <<'DOISMODOSEOF'
import os
import re
cfg = "airootfs/etc/skel/.config/i3/config"
ksc = "airootfs/usr/local/bin/stylus-kde-shortcuts"
apps = "airootfs/usr/share/applications"
if not (os.path.isfile(cfg) and os.path.isfile(ksc)):
    print("PULA sem o config do i3 ou o stylus-kde-shortcuts")
    raise SystemExit(0)


def programa(cmd):
    """O comando de verdade por trás de uma linha do i3 ou de um Exec."""
    cmd = re.sub(r"^exec\s+(--no-startup-id\s+)?", "", cmd.strip())
    cmd = re.sub(r"^\$?termrun\s+\S+\s+|^stylus-term\s+\S+\s+", "", cmd)
    cmd = re.sub(r'^"[^"]*"\s+', "", cmd)
    cmd = cmd.replace("sudo ", "")
    partes = cmd.split()
    if not partes:
        return ""
    # `stylus record` e `stylus-record` são a mesma coisa para esta pergunta.
    nome = partes[0]
    if nome == "stylus" and len(partes) > 1 and not partes[1].startswith("-"):
        nome = "stylus-" + partes[1]
    return os.path.basename(nome)


i3 = {}
with open(cfg, encoding="utf-8") as fh:
    for ln in fh:
        m = re.match(r"^bindsym\s+\$mod\+(\S+)\s+(.*)$", ln)
        if m:
            tecla = "+".join(p.capitalize() if p.lower() in ("shift", "control", "ctrl")
                             else p for p in m.group(1).split("+"))
            tecla = tecla.replace("Control", "Ctrl")
            i3.setdefault(tecla.lower(), programa(m.group(2)))

problemas = []
with open(ksc, encoding="utf-8") as fh:
    for ln in fh:
        m = re.match(r'^atalho\s+(\S+)\s+"Meta\+(\S+)"', ln)
        if not m:
            continue
        desk, tecla = m.group(1), m.group(2).replace("Control", "Ctrl")
        caminho = os.path.join(apps, desk)
        if not os.path.isfile(caminho):
            problemas.append("%s: o %s não existe" % (tecla, desk))
            continue
        alvo = ""
        with open(caminho, encoding="utf-8") as dh:
            for dl in dh:
                if dl.startswith("Exec="):
                    alvo = programa(dl[5:])
                    break
        outro = i3.get(tecla.lower())
        if outro and alvo and outro != alvo:
            problemas.append("Meta+%s abre %s no KDE e %s no i3"
                             % (tecla, alvo, outro))
if problemas:
    print("ERRO " + " | ".join(problemas))
else:
    print("OK as teclas do KDE não contradizem as do i3")
DOISMODOSEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "o mesmo atalho faz coisas diferentes em cada modo"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "sortear um disco põe o disco para tocar"
# **Sintoma:** `stylus record --play` respondia "o lançador `vinyl` não está
# instalado" e parava. O `~/.local/bin/vinyl` não é instalado por este
# repositório e nunca foi — era o lançador da máquina de quem escreveu. Pior:
# o atalho `Mod+Shift+O` do i3 roda exatamente esse comando SEM terminal, e
# apertar a tecla não fazia absolutamente nada, sem uma palavra em lugar
# nenhum.
#
# Esta conferência RODA o comando com um `stylus-deck` de mentira no PATH e
# olha o que chegou nele. Ler não pega: o caminho estava escrito com todas as
# letras e parecia um lançador plausível.
RECTEST=airootfs/usr/share/stylus/tools/record.py
if [[ -f $RECTEST ]] && python3 -c 'import mutagen' 2>/dev/null; then
    RECDIR=$(mktemp -d)
    mkdir -p "$RECDIR/bin" "$RECDIR/casa"
    cat > "$RECDIR/bin/stylus-deck" <<'DECKEOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$FALSO/chamou"
DECKEOF
    chmod +x "$RECDIR/bin/stylus-deck"
    python3 - "$RECDIR" <<'WAVRECEOF'
import os, struct, sys, wave
d = os.path.join(sys.argv[1], "estante", "Artista", "Disco")
os.makedirs(d, exist_ok=True)
quadro = struct.pack("<h", 0) * 8000
for i in range(1, 7):
    with wave.open(os.path.join(d, "%02d faixa.wav" % i), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(quadro * 200)
WAVRECEOF
    saida=$(env PATH="$RECDIR/bin:/usr/bin:/bin" HOME="$RECDIR/casa" \
            FALSO="$RECDIR" STYLUS_LIBRARY="$RECDIR/estante" \
            PYTHONPATH="airootfs/usr/share/stylus/deck:airootfs/usr/share/stylus/tools" \
            python3 "$RECTEST" --play 2>&1)
    if [[ ! -f $RECDIR/chamou ]]; then
        bad "\`stylus record --play\` não chegou a pôr disco nenhum:"
        # Sem as linhas em branco e sem a lista de faixas, que é o grosso da
        # saída: o que interessa é a última coisa que ele DISSE.
        printf '%s\n' "$saida" | grep -vE '^\s*$|faixa' | tail -3 |
            sed 's/^/      /'
    elif ! grep -q "Disco" "$RECDIR/chamou"; then
        bad "o disco sorteado não chegou ao tocador: $(tr '\n' ' ' < "$RECDIR/chamou")"
    elif ! grep -q -- "--no-scope" "$RECDIR/chamou"; then
        bad "--play abriu o deck com tela (era para ser --no-scope)"
    else
        ok "o disco sorteado chega ao stylus-deck, sem tela"
    fi
    rm -rf "$RECDIR"
else
    printf '  %s—%s sem mutagen aqui; o sorteio não foi exercitado\n' "$y" "$z"
fi

sec "trocar de playlist do Qobuz troca o disco na mão do vigia"
# **Sintoma:** o `dirname` de um ENDEREÇO é a mesma string para toda playlist
# do Qobuz ("https:/o-servidor"), e o stylus-side-watch usava isso como chave
# de "trocou de disco?". Ele ficava com a playlist ANTERIOR na mão: o "vira
# em X", o aviso de fim de lado e a agulha.tsv falavam da lista de antes, e a
# renovação da assinatura chegava a pendurar a cauda dela na fila do mpv — da
# poltrona, a música troca de disco sozinha.
saida=$(python3 - <<'VIGIAEOF' 2>&1
import importlib.machinery as im, importlib.util, os, shutil, sys, tempfile
import traceback
sys.path.insert(0, "airootfs/usr/share/stylus/deck")
try:
    spec = importlib.util.spec_from_loader(
        "sw", im.SourceFileLoader("sw", "airootfs/usr/local/bin/stylus-side-watch"))
    sw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sw)
except BaseException as e:                               # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)

tmp = tempfile.mkdtemp()
os.environ["HOME"] = tmp
sw.AGULHA = os.path.join(tmp, "agulha.tsv")

URL = {"A": "https://o-servidor.invalid/a%d.flac",
       "B": "https://o-servidor.invalid/b%d.flac"}


class AlbumFalso:
    def __init__(self, pasta):
        self.folder = pasta
        letra = os.path.basename(pasta)
        self.tracks = [{"path": URL[letra] % i, "title": "t%d" % i,
                        "duration": 300.0, "start": i * 300.0}
                       for i in range(6)]
        self.total = 1800.0
        self.sides = [{"label": "LADO A", "start": 0.0, "end": 900.0,
                       "tracks": [0, 1, 2]},
                      {"label": "LADO B", "start": 900.0, "end": 1800.0,
                       "tracks": [3, 4, 5]}]

    def album_time(self, idx, pos):
        return self.tracks[idx]["start"] + (pos or 0.0)

    def side_for(self, t):
        for i, sd in enumerate(self.sides):
            if sd["start"] <= t < sd["end"]:
                return i, sd
        return len(self.sides) - 1, self.sides[-1]


class SessaoFalsa:
    agora = URL["A"] % 0

    def snapshot(self):
        return {"path": SessaoFalsa.agora, "artist": "", "album": "",
                "paused": False}

    def position(self):
        return 10.0, 300.0


sw.vinyl.Session = lambda: SessaoFalsa()
sw.vinyl.resolve_album = lambda path=None, artist="", album="": os.path.join(
    tmp, "B" if "/b" in path else "A")
sw.vinyl.Album = lambda f, envelope=False: AlbumFalso(f)
try:
    olho = sw.Olho()
    olho.onde()
    primeiro = os.path.basename(olho.album.folder)
    # a MESMA playlist, faixa seguinte: não pode reabrir nada
    SessaoFalsa.agora = URL["A"] % 3
    olho.onde()
    mesmo = os.path.basename(olho.album.folder)
    # outra playlist, mesmo servidor: TEM que trocar
    SessaoFalsa.agora = URL["B"] % 0
    olho.onde()
    segundo = os.path.basename(olho.album.folder)
    if primeiro != "A":
        print("ERRO nem o primeiro disco resolveu: %s" % primeiro)
    elif mesmo != "A":
        print("ERRO trocou de disco andando na MESMA lista")
    elif segundo != "B":
        print("ERRO ficou com a playlist anterior na mão (%s)" % segundo)
    else:
        print("OK a lista nova entra e a faixa seguinte não reabre nada")
except Exception:                                        # noqa: BLE001
    print("ERRO %s" % traceback.format_exc().replace("\n", " | "))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
VIGIAEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s sem o stylus-side-watch aqui: %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "o vigia do lado erra o disco quando a playlist troca"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "o aviso de virar o disco dura mais que um aviso de volume"
# O padrão do dunst para urgência normal são OITO SEGUNDOS, e o fim do lado é
# o aviso de que a coisa toda existe. Oito segundos é tempo de aviso de
# volume — e quem está ouvindo um disco é justamente quem não está na frente
# do computador. Da cozinha, o recado já era.
#
# Três lugares, na verdade: o tempo do dunst, o do vigia e o do aviso da tela
# cheia (FLIP_DUR) — que é o ÚNICO quando a interface está aberta, porque
# nesse caso o vigia não manda notificação nenhuma.
saida=$(python3 - <<'ESPERAEOF' 2>&1
import re
try:
    dunst = open("airootfs/etc/skel/.config/dunst/dunstrc",
                 encoding="utf-8").read()
    vigia = open("airootfs/usr/local/bin/stylus-side-watch",
                 encoding="utf-8").read()
except OSError as e:
    print("PULA %s" % e)
    raise SystemExit(0)
m = re.search(r"\[urgency_normal\](.*?)(\n\[|\Z)", dunst, re.S)
padrao = int(re.search(r"^\s*timeout\s*=\s*(\d+)", m.group(1), re.M).group(1))
mv = re.search(r"^ESPERA_LADO\s*=\s*([\d_]+)", vigia, re.M)
if not mv:
    print("ERRO o vigia não define ESPERA_LADO")
    raise SystemExit(0)
espera = int(mv.group(1).replace("_", "")) / 1000.0
# E a chamada do fim do lado tem que USAR isso — não adianta a constante
# existir e o aviso sair no padrão, que é a família do helper que ninguém
# chama. Só linha de código, nunca comentário.
usa = any("avisar(titulo, corpo, espera=" in ln
          for ln in vigia.splitlines() if not ln.lstrip().startswith("#"))
try:
    app = open("airootfs/usr/share/stylus/ui/app.py", encoding="utf-8").read()
    cheia = float(re.search(r"^\s*FLIP_DUR\s*=\s*([\d.]+)", app, re.M).group(1))
except (OSError, AttributeError):
    cheia = 0.0
if espera <= padrao:
    print("ERRO o aviso do lado dura %gs e o padrão do dunst é %gs"
          % (espera, padrao))
elif not usa:
    print("ERRO o ESPERA_LADO existe e o aviso do fim do lado não o usa")
elif cheia < espera / 2000.0:
    print("ERRO na tela cheia o mesmo aviso dura %gs (o da área de trabalho, %gs)"
          % (cheia, espera))
else:
    print("OK %gs na área de trabalho e %gs na tela cheia, contra os %gs de "
          "um aviso qualquer" % (espera, cheia, padrao))
ESPERAEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "o aviso de virar o disco some rápido demais"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "toda tecla que o rofi anuncia tem um destino"
# **Sintoma:** o `Alt+s` da estante — tocar a playlist do Qobuz em ordem
# SORTEADA, anunciada no cabeçalho do próprio arquivo — apenas FECHAVA a
# estante. O rofi devolve 9+N para o `-kb-custom-N`, o Alt+s é o custom-5, e o
# `case` que filtra os códigos ia só até o 13: o 14 caía no `*) exit 0`. O
# recado "só playlist se sorteia", escrito logo abaixo, nunca apareceu na tela
# de ninguém.
#
# É a família do módulo da polybar que não estava em `modules-*`: a peça
# existe, está certa, e a lista que a chama não a conhece.
saida=$(python3 - <<'ROFIEOF' 2>&1
import os
import re
falhas = []
for base in ("airootfs/usr/local/bin", "airootfs/etc/skel/.config/rofi"):
    for d, _s, fs in os.walk(base):
        for nome in fs:
            cam = os.path.join(d, nome)
            try:
                with open(cam, encoding="utf-8", errors="replace") as fh:
                    txt = fh.read()
            except OSError:
                continue
            custom = {int(m) for m in re.findall(r"-kb-custom-(\d+)", txt)}
            if not custom:
                continue
            codigos = {9 + n for n in custom}
            # O que interessa é o FILTRO, não o tratamento: quem tem um
            # `case $rc in 0|10|…) ;; *) exit` decide ali quais códigos
            # sobrevivem, e um código de fora morre antes de chegar ao
            # `(( rc == N ))` que o trataria — que foi exatamente o defeito.
            # Se o arquivo tem esse filtro, ele é a lista que vale.
            passa, tem_filtro = set(), False
            for ln in txt.splitlines():
                if ln.lstrip().startswith("#"):
                    continue
                if re.match(r"\s*[\d|]+\)\s*;;\s*$", ln):
                    tem_filtro = True
                    for m in re.findall(r"\d+", ln.split(")")[0]):
                        passa.add(int(m))
            if not tem_filtro:
                for ln in txt.splitlines():
                    if ln.lstrip().startswith("#"):
                        continue
                    for m in re.findall(r"rc\s*==\s*(\d+)", ln):
                        passa.add(int(m))
            faltam = sorted(codigos - passa)
            if faltam:
                falhas.append("%s: %s (custom-%s)"
                              % (cam, faltam,
                                 ", ".join(str(c - 9) for c in faltam)))
if falhas:
    print("ERRO " + " | ".join(falhas))
else:
    print("OK todo -kb-custom tem o código de saída tratado")
ROFIEOF
)
case "$saida" in
    OK*) ok "${saida#OK }" ;;
    *)   bad "tecla do rofi sem destino:"
         printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "letra maiúscula anunciada é tecla com Shift"
# O `frase_com_teclas` desenha a letra dentro de uma tampinha, então um `[D]`
# na tela se lê como Shift+D. Três anúncios estavam em maiúscula sobre teclas
# que não pedem Shift nenhum — o `[D]` do "deck sozinho" e o `[N]`/`[P]` do
# Spotify —, enquanto o `[R]` (repetir) e o `[L]` (playlists) pedem mesmo. A
# tampinha é o contrato: se está em maiúscula, tem que ter Shift no
# tratamento.
saida=$(python3 - <<'MAIUSEOF' 2>&1
import re
try:
    app = open("airootfs/usr/share/stylus/ui/app.py", encoding="utf-8").read()
except OSError as e:
    print("PULA %s" % e)
    raise SystemExit(0)
linhas = app.splitlines()
# Onde cada letra é tratada COM Shift.
com_shift = set()
for ln in linhas:
    m = re.search(r"pygame\.K_([a-z])\b.*KMOD_SHIFT", ln)
    if m:
        com_shift.add(m.group(1).upper())
# O que a tela anuncia em maiúscula. Sem comentário e SEM DOCSTRING: as
# explicações deste arquivo citam as teclas o tempo todo ("o `[X]` de teclas
# vira quadradinho"), e contá-las faria a conferência acusar a prosa que
# explica o defeito — a mesma armadilha de sempre.
import ast
docs = set()
for no in ast.walk(ast.parse(app)):
    if isinstance(no, ast.Expr) and isinstance(no.value, ast.Constant) \
            and isinstance(no.value.value, str):
        docs.update(range(no.lineno, (no.end_lineno or no.lineno) + 1))
falhas = set()
for n, ln in enumerate(linhas, 1):
    if ln.lstrip().startswith("#") or n in docs:
        continue
    for m in re.findall(r"\[([A-Z])\]", ln):
        if m not in com_shift:
            falhas.add(m)
if falhas:
    print("ERRO anunciadas em maiúscula e tratadas sem Shift: %s"
          % ", ".join(sorted(falhas)))
else:
    print("OK as maiúsculas anunciadas (%s) pedem Shift mesmo"
          % ", ".join(sorted(com_shift)) if com_shift else
          "OK nenhuma tecla anunciada em maiúscula")
MAIUSEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "a tampinha da tecla mente sobre o Shift"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "o sync não sai andando pela casa inteira"
# **Sintoma:** o /etc/skel tem seis arquivos na RAIZ da casa (.bashrc,
# .xinitrc, .dialogrc…). Para qualquer um deles que ainda não existisse, o
# `chown -R "$usuario": "$(dirname "$alvo")"` do sync.sh recebia a CASA
# inteira: ele saía andando pela coleção de música com cem mil arquivos, pelos
# caches, pelo .git de quem clonou o repositório — e pelo celular montado por
# WebDAV, atravessado arquivo por arquivo pela rede. Minutos de espera no meio
# de um `stylus-update`, sem uma linha na tela dizendo o que era.
#
# A regra: `chown -R` no sync.sh só sobre caminho ESCRITO (uma pasta nossa,
# pequena e conhecida), nunca sobre um `dirname` calculado.
SYNC=airootfs/usr/share/stylus/sync.sh
if [[ -f $SYNC ]]; then
    ruim=$(grep -n 'chown -R' "$SYNC" | grep -v '^\s*#' | grep 'dirname' || true)
    if [[ -z $ruim ]]; then
        # E o /etc/skel tem MESMO arquivo na raiz? Se um dia não tiver, a
        # conferência continua valendo — mas é bom o motivo estar à vista.
        n=$(find airootfs/etc/skel -maxdepth 1 -type f | wc -l)
        ok "nenhum chown -R sobre pasta calculada ($n arquivos na raiz do skel)"
    else
        bad "chown -R sobre uma pasta calculada (pode ser a casa inteira):"
        printf '%s\n' "$ruim" | sed 's/^/      /'
    fi
else
    printf '  %s—%s sem o sync.sh\n' "$y" "$z"
fi

sec "o que a instalação copia, a atualização também copia"
# Duas listas escritas à mão para o mesmo trabalho: o branding-sync.sh leva o
# STYLUS para um sistema recém-instalado, o sync.sh leva para um sistema que
# já existe. Elas tinham DERIVADO — o GRUB, o plymouth, o tema do SDDM e os
# ícones estavam só na primeira. Quem instalou há dois meses e rodou
# `stylus-update` recebia a paleta nova em tudo menos nas TRÊS PRIMEIRAS
# telas que a máquina desenha.
#
# O que fica de fora fica com o motivo escrito aqui, e não por esquecimento.
saida=$(python3 - <<'DUASEOF' 2>&1
import re
try:
    bs = open("airootfs/usr/share/stylus/branding-sync.sh",
              encoding="utf-8").read()
    sy = open("airootfs/usr/share/stylus/sync.sh", encoding="utf-8").read()
except OSError as e:
    print("PULA %s" % e)
    raise SystemExit(0)

# O que a instalação copia (só linha de código).
copiados = []
for ln in bs.splitlines():
    if ln.lstrip().startswith("#"):
        continue
    m = re.match(r'\s*copiar\s+"?([^"\s]+)"?', ln)
    if m and "$" not in m.group(1):
        copiados.append(m.group(1))

# O que a atualização copia: a lista, mais os caminhos escritos à mão nela.
lista = re.search(r"SYSTEM_PATHS=\(\n(.*?)\n\)", sy, re.S)
# Sem o comentário de fim de linha: no bash, um `#` depois de espaço dentro
# de um array começa comentário — e sem tirá-lo aqui a conferência não
# reconhecia a própria linha que ela pediu para existir.
cobertos = []
for ln in lista.group(1).splitlines():
    nu = ln.split("#")[0].strip()
    if nu:
        cobertos.append(nu)
cobertos += re.findall(r'"\$SRC/(etc/[^"]+)"', sy)
cobertos += re.findall(r"\$SRC/(etc/systemd/system)/stylus-", sy)

# O que é do MEDIUM AO VIVO e não pode ir para um sistema instalado.
FORA = {
    "etc/sddm.conf.d/stylus.conf":
        "tem [Autologin] User=stylus, que o instalador apaga de propósito",
    "etc/skel":
        "é a parte 2 do sync.sh, com a regra do pacman",
    "etc/stylus":
        "nasce no build; a máquina instalada tem a estante da pessoa",
}
faltando = []
for c in copiados:
    if c in FORA:
        continue
    if any(c == k or c.startswith(k.rstrip("/") + "/") for k in cobertos):
        continue
    faltando.append(c)
if faltando:
    print("ERRO a instalação copia e a atualização não: %s"
          % ", ".join(sorted(set(faltando))))
else:
    print("OK %d caminhos da instalação chegam pela atualização também"
          % len(copiados))
DUASEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "a atualização não leva o que a instalação leva"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "a tela de arranque está na paleta"
# A conferência de deriva pega cor QUASE igual a uma da paleta; uma cor de
# outra paleta inteira ela deixa passar de propósito ("ou é igual, ou é
# claramente outra cor"). Só que a tela de arranque tem três cores no total, e
# as três eram de outra paleta: fundo VERDE e texto branco-esverdeado. Aqui a
# régua é a estrita — o que este arquivo pinta tem que SER uma cor da paleta.
saida=$(python3 - <<'ARRANQUEEOF' 2>&1
import re
try:
    pal = {}
    for ln in open("airootfs/usr/share/stylus/palette", encoding="utf-8"):
        m = re.match(r"^([A-Z_]+)=#([0-9a-fA-F]{6})\s*$", ln)
        if m:
            pal[m.group(2).lower()] = m.group(1)
    txt = open("airootfs/usr/share/plymouth/themes/stylus/stylus.script",
               encoding="utf-8").read()
except OSError as e:
    print("PULA %s" % e)
    raise SystemExit(0)
fora = []
for ln in txt.splitlines():
    if ln.lstrip().startswith("#"):
        continue
    for m in re.finditer(r"\(\s*(\d\.\d{1,4})\s*,\s*(\d\.\d{1,4})"
                         r"\s*,\s*(\d\.\d{1,4})\s*\)", ln):
        f = tuple(float(x) for x in m.groups())
        h = "%02x%02x%02x" % tuple(int(round(x * 255)) for x in f)
        if h not in pal:
            fora.append("%s (#%s)" % (m.group(0), h))
if fora:
    print("ERRO cor fora da paleta na tela de arranque: %s" % ", ".join(fora))
else:
    print("OK as cores da tela de arranque são as da paleta")
ARRANQUEEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "a primeira tela da máquina não está na paleta"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "o tema que o sistema instala é o tema que ele escolhe"
# **Sintoma:** o tema do plymouth existe no repositório (logo.png,
# stylus.script), o hook `plymouth` está na linha de HOOKS do mkinitcpio, o
# pacote está nas duas listas — e NADA nunca escolheu o tema. O plymouth caía
# no padrão dele: a tela entre o GRUB e o login era a de fábrica, e o desenho
# do STYLUS nunca foi visto ali por ninguém. É a família do stylus-welcome —
# a peça inteira pronta, faltando o fio.
#
# A regra, escrita de forma que valha para o próximo tema também: para cada
# tema que o repositório traz em usr/share/<coisa>/themes/stylus, alguém tem
# que ESCOLHÊ-LO em algum lugar.
saida=$(python3 - <<'TEMAEOF' 2>&1
import os
import re
alvos = {
    "grub": ("usr/share/grub/themes/stylus",
             r"GRUB_THEME=.*themes/stylus"),
    "plymouth": ("usr/share/plymouth/themes/stylus",
                 r"plymouth-set-default-theme\s+stylus|Theme=stylus"),
    "sddm": ("usr/share/sddm/themes/stylus",
             r"^\s*Current\s*=\s*stylus"),
}
fontes = []
for base in ("airootfs/usr/local/bin", "airootfs/etc", "airootfs/usr/share/stylus"):
    for d, _s, fs in os.walk(base):
        if "__pycache__" in d:
            continue
        for n in fs:
            cam = os.path.join(d, n)
            try:
                with open(cam, encoding="utf-8", errors="replace") as fh:
                    fontes.append((cam, fh.read()))
            except OSError:
                continue
faltam = []
for nome, (pasta, padrao) in alvos.items():
    if not os.path.isdir(os.path.join("airootfs", pasta)):
        continue
    rx = re.compile(padrao, re.M)
    achou = False
    for cam, txt in fontes:
        for ln in txt.splitlines():
            if ln.lstrip().startswith("#"):
                continue
            if rx.search(ln):
                achou = True
                break
        if achou:
            break
    if not achou:
        faltam.append(nome)
if faltam:
    print("ERRO tema no repositório e ninguém o escolhe: %s"
          % ", ".join(sorted(faltam)))
else:
    print("OK os %d temas que o repositório traz são escolhidos em algum lugar"
          % len(alvos))
TEMAEOF
)
case "$saida" in
    OK*) ok "${saida#OK }" ;;
    *)   bad "tema instalado e nunca escolhido:"
         printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "a loja de tela cheia mostra TODOS os favoritos"
# **Sintoma (relatado):** "a loja não mostra todos os discos salvos". Havia
# DUAS frentes para a mesma loja — a estante do rofi e a tela cheia — e só a
# primeira tinha aprendido a paginar: aqui a chamada era uma só, com
# `limit=60`. Quem tem 87 favoritos via 60, sem nada dizendo que havia mais,
# enquanto a estante do rofi ao lado mostrava os 87. E a BUSCA pedia 25
# resultados contra os 100 de lá.
#
# A conferência roda o caminho da tela cheia contra um Qobuz de mentira com
# 237 favoritos e conta o que chegou do outro lado.
saida=$(python3 - <<'FAVCHEIAEOF' 2>&1
import sys
sys.path.insert(0, "airootfs/usr/share/stylus")
N = 237


class Cli:
    sec = "x"

    def __init__(self):
        self.chamadas = []

    def api_call(self, _rota, type=None, offset=0, limit=50, sec=None):
        self.chamadas.append((offset, limit))
        itens = [{"id": i, "title": "Disco %d" % i,
                  "artist": {"name": "Artista %d" % i}, "tracks_count": 10,
                  "maximum_bit_depth": 24, "maximum_sampling_rate": 96,
                  "release_date_original": "2001-01-01",
                  "image": {"large": "http://x/%d.jpg" % i}}
                 for i in range(offset, min(N, offset + limit))]
        return {"albums": {"items": itens, "total": N}}

    def search_albums(self, _termo, limit=25):
        self.chamadas.append(("busca", limit))
        return {"albums": {"items": []}}


try:
    import qobuz_busca as qb
except Exception as e:                                   # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)
cl = Cli()
qb.cliente = lambda: cl
saida = []
qb.responde = lambda **k: (saida.append(k), (_ for _ in ()).throw(SystemExit))
try:
    sys.argv = ["qobuz_busca.py", "favoritos"]
    qb.main()
except SystemExit:
    pass
res = (saida[-1] if saida else {}).get("results") or []
cl2 = Cli()
qb.cliente = lambda: cl2
saida[:] = []
try:
    sys.argv = ["qobuz_busca.py", "buscar", "beatles"]
    qb.main()
except SystemExit:
    pass
pedido = [c for c in cl2.chamadas if c and c[0] == "busca"]
if len(res) != N:
    print("ERRO a loja mostrou %d dos %d favoritos" % (len(res), N))
elif len(cl.chamadas) < 2:
    print("ERRO pediu uma página só (%s)" % cl.chamadas)
elif not pedido or pedido[0][1] < 100:
    print("ERRO a busca pede %s resultados (a do rofi pede 100)"
          % (pedido[0][1] if pedido else "?"))
else:
    print("OK %d favoritos em %d páginas, e a busca pede %d"
          % (len(res), len(cl.chamadas), pedido[0][1]))
FAVCHEIAEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s sem o qobuz_busca aqui: %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "a loja de tela cheia não mostra tudo que você salvou"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "o celular e o computador concordam sobre o que é música"
# A SÉTIMA cópia da lista de extensões de áudio morava no Library.kt do
# celular, e discordava: faltavam .wma, .shn e .ape. Uma coleção com rip
# antigo (Windows Media, Shorten, Monkey's Audio) ficava invisível no
# aparelho — sem erro nenhum, que é o pior jeito de não funcionar. A mesma
# doença das seis listas do computador, atravessando para o outro lado.
saida=$(python3 - <<'EXTKTEOF' 2>&1
import re
import sys
sys.path.insert(0, "airootfs/usr/share/stylus/deck")
try:
    import vinyl
    kt = open("android/app/src/main/kotlin/io/stylus/player/Library.kt",
              encoding="utf-8").read()
except Exception as e:                                   # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)
m = re.search(r"AUDIO_EXT\s*=\s*setOf\((.*?)\)", kt, re.S)
if not m:
    print("ERRO não achei o AUDIO_EXT do Library.kt")
    raise SystemExit(0)
do_kt = set(re.findall(r'"(\.[a-z0-9]+)"', m.group(1)))
do_py = set(vinyl.AUDIO_EXT)
falta = sorted(do_py - do_kt)
sobra = sorted(do_kt - do_py)
if falta or sobra:
    print("ERRO o celular %s%s%s"
          % ("não conhece %s" % ", ".join(falta) if falta else "",
             " e " if falta and sobra else "",
             "conhece %s a mais" % ", ".join(sobra) if sobra else ""))
else:
    print("OK as %d extensões são as mesmas nos dois lados" % len(do_py))
EXTKTEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "as duas metades da coleção discordam sobre o que é música"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "o texto do celular é o mesmo português do computador"
# **Sintoma:** "Nenhuma musica encontrada", "12 albuns", "Saidas", e um
# "Bit-perfect audio for Android" em inglês na tela SOBRE. Texto que o
# usuário vê é em português, e é o MESMO português dos dois lados — a coleção
# é a mesma, o vocabulário também tem que ser. E a regra do plural mora no
# `Texto.plural`, irmão do `model.plural` do lançador: "1 albuns" é o mesmo
# defeito que custou quinze lugares lá.
saida=$(python3 - <<'TEXTOKTEOF' 2>&1
import os
import re
raiz = "android/app/src/main/kotlin/io/stylus/player"
if not os.path.isdir(raiz):
    print("PULA sem o app do celular aqui")
    raise SystemExit(0)
# Palavras portuguesas que perderam o acento, e o plural escrito à mão.
sem_acento = re.compile(
    r'"[^"]*\b(musica|musicas|albuns|saidas|sera|ultimo|proxima|'
    r'nao|voce|tres|numero|automatico|cancao|memoria)\b[^"]*"')
# O que está DENTRO de uma interpolação é código, não texto: `${album.name}`
# tem a palavra "album" e não é o usuário que a lê. Sem tirar isso, a
# conferência acusa toda linha que monta um título — que é o oposto de
# ajudar.
interp = re.compile(r"\$\{[^}]*\}|\$[A-Za-z_]\w*")
mao = re.compile(r'\$\{?[A-Za-z_][\w.()]*\}?\s+'
                 r'(faixas|discos|albuns|álbuns|vezes|lados|resultados)\b')
achados = []
for nome in sorted(os.listdir(raiz)):
    if not nome.endswith(".kt"):
        continue
    cam = os.path.join(raiz, nome)
    with open(cam, encoding="utf-8") as fh:
        for n, ln in enumerate(fh, 1):
            # Comentário de bloco também: a explicação DESTE defeito cita
            # "1 albuns" com todas as letras, e a conferência que acusa a
            # própria explicação do conserto é uma que se aprende a ignorar.
            if ln.lstrip().startswith(("*", "/*")):
                continue
            nu = interp.sub(" ", ln.split("//")[0])
            if sem_acento.search(nu):
                achados.append("%s:%d sem acento" % (nome, n))
            elif mao.search(nu):
                achados.append("%s:%d plural à mão (use Texto.plural)"
                               % (nome, n))
if achados:
    print("ERRO " + " | ".join(achados[:6]))
else:
    print("OK acento e plural, nos %d arquivos do app"
          % len([n for n in os.listdir(raiz) if n.endswith(".kt")]))
TEXTOKTEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "o texto do celular não é o do computador"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

sec "a tela que desenha o som não reamostra a música"
# **Sintoma (relatado):** a tela SINAL mostrava a música sendo REAMOSTRADA.
#
# O monitor da tela cheia abria a captura do PipeWire em 48000 escrito à mão
# e a mantinha aberta o tempo todo. Duas consequências, as duas contra a
# única promessa da máquina:
#
#   · numa coleção que é quase toda 44,1k, essa captura é um segundo fluxo
#     pedindo OUTRA taxa em cima do disco que está tocando;
#   · e a placa nunca ficava ociosa, então o `session.suspend-timeout-
#     seconds = 1` do wireplumber nunca vencia e o dispositivo não podia ser
#     reaberto na taxa do disco seguinte.
#
# Ou seja: a tela que desenha o som desfazia a tese do sistema, e a tela
# SINAL, ao lado, mostrava o resultado sem saber a causa.
#
# Esta conferência roda o monitor com um PortAudio de mentira e olha três
# coisas: em que taxa ele abre, se solta a placa no silêncio, e se acompanha
# a taxa quando ela muda.
saida=$(python3 - <<'MONEOF' 2>&1
import sys
import time
import types
sys.path.insert(0, "airootfs/usr/share/stylus/ui")
try:
    import numpy as np
except Exception as e:                                   # noqa: BLE001
    print("PULA sem numpy: %s" % e)
    raise SystemExit(0)

SILENCIO = [False]


class Fluxo:
    def __init__(self, rate):
        self.rate, self.rodando = rate, False

    def start_stream(self):
        self.rodando = True

    def stop_stream(self):
        self.rodando = False

    def read(self, n, exception_on_overflow=True):
        return (b"\x00\x00" if SILENCIO[0] else b"\x10\x27") * 2 * n


class PA:
    def __init__(self):
        self.abertos = []

    def get_device_count(self):
        return 1

    def get_device_info_by_index(self, _i):
        return {"name": "pulse", "maxInputChannels": 2}

    def open(self, **kw):
        f = Fluxo(kw["rate"])
        self.abertos.append(f)
        return f


falso = types.ModuleType("pyaudio")
falso.paInt16 = 8
falso.PyAudio = PA
sys.modules["pyaudio"] = falso
try:
    import audio_live as al
except Exception as e:                                   # noqa: BLE001
    print("PULA %s" % e)
    raise SystemExit(0)
al.pyaudio, al.np = falso, np
TAXA = [44100]
al.taxa_do_grafo = lambda: TAXA[0]
# Só há monitor RODANDO quando há som — é assim que o pactl responde.
al.find_monitor_source = lambda so_rodando=False: (
    None if (so_rodando and SILENCIO[0]) else "monitor.falso")
try:
    m = al.AudioMonitor()
    time.sleep(0.5)
    abriu = m._taxa
    SILENCIO[0] = True
    time.sleep(1.8)
    soltou = m._stream is None
    TAXA[0] = 96000
    SILENCIO[0] = False
    time.sleep(1.2)
    seguiu = m._taxa
    taxas = [f.rate for f in m._p.abertos]
    m._stop = True
    if abriu != 44100:
        print("ERRO abriu em %s com o grafo em 44100" % abriu)
    elif not soltou:
        print("ERRO continuou segurando a placa no silêncio")
    elif seguiu != 96000:
        print("ERRO não acompanhou a taxa nova (ficou em %s)" % seguiu)
    elif taxas != [44100, 96000]:
        print("ERRO abriu fluxos demais: %s" % taxas)
    else:
        print("OK abre na taxa do grafo, solta no silêncio e segue a troca")
except Exception as e:                                   # noqa: BLE001
    import traceback
    print("ERRO %s" % traceback.format_exc().replace("\n", " | "))
MONEOF
)
case "$saida" in
    OK*)   ok "${saida#OK }" ;;
    PULA*) printf '  %s—%s %s\n' "$y" "$z" "${saida#PULA }" ;;
    *)     bad "o monitor da tela cheia força a reamostragem"
           printf '%s\n' "$saida" | sed 's/^/      /' ;;
esac

printf '\n  %s%d passaram%s' "$g" "$PASS" "$z"
(( FAIL )) && printf ', %s%d falharam%s\n\n' "$r" "$FAIL" "$z" || printf '\n\n'
exit $(( FAIL > 0 ))
