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
        --exclude=README.md --exclude=CLAUDE.md \
        -e 'IFOS' -e 'ifos-' -e '\bifos\b' . 2>/dev/null || true)
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
mapfile -t SKELF < <(find airootfs/etc/skel -type f; echo airootfs/usr/share/stylus/i3-music.config)
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

printf '\n  %s%d passaram%s' "$g" "$PASS" "$z"
(( FAIL )) && printf ', %s%d falharam%s\n\n' "$r" "$FAIL" "$z" || printf '\n\n'
exit $(( FAIL > 0 ))
