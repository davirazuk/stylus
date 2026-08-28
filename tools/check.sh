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
if [[ -f $LISTA_INST ]]; then
    TERMDEF=$(sed -n 's/^set \$term  *//p' airootfs/etc/skel/.config/i3/config | awk '{print $1}')
    if [[ -z $TERMDEF ]]; then
        bad "a config do i3 não define \$term"
    elif nomes "$LISTA_INST" | grep -qx "$TERMDEF" && nomes "$LISTA_ISO" | grep -qx "$TERMDEF"; then
        ok "o terminal do Mod+Enter ($TERMDEF) está nas duas listas de pacote"
    else
        bad "\$term é '$TERMDEF', que não está nas duas listas — Mod+Enter não abre nada"
    fi
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
RAIZES = ["airootfs/etc/skel",
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

printf '\n  %s%d passaram%s' "$g" "$PASS" "$z"
(( FAIL )) && printf ', %s%d falharam%s\n\n' "$r" "$FAIL" "$z" || printf '\n\n'
exit $(( FAIL > 0 ))
