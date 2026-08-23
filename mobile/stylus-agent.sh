#!/data/data/com.termux/files/usr/bin/sh
# ═══════════════════════════════════════════════════════════════════════════
#  stylus-agent — o lado do celular
# ═══════════════════════════════════════════════════════════════════════════
#      sh stylus-agent.sh install    prepara o sshd e a chave
#      sh stylus-agent.sh start      liga o sshd
#      sh stylus-agent.sh status     endereço e porta
#      sh stylus-agent.sh scrobbles  exporta o que você ouviu, para o PC ler
# ═══════════════════════════════════════════════════════════════════════════
set -u
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
PORTA=8022
SAIDA=/sdcard/stylus-scrobbles.tsv

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  !\033[0m %s\n' "$*"; }

ip_do_wifi() {
    ip route 2>/dev/null | awk '/src/ {for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1
}

cmd_install() {
    info "Pacotes…"
    pkg install -y openssh rsync termux-api >/dev/null 2>&1 || \
        warn "instale à mão: pkg install openssh rsync termux-api"
    # O sshd do Termux usa chave, não senha — e é melhor assim: senha de
    # celular numa rede de casa é a definição de "vai dar errado um dia".
    mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"
    touch "$HOME/.ssh/authorized_keys"; chmod 600 "$HOME/.ssh/authorized_keys"
    info "Ligando o acesso ao armazenamento…"
    termux-setup-storage 2>/dev/null || true
    ok "pronto"
    printf '\n  no PC, mande a sua chave para cá:\n'
    printf '    \033[2mssh-copy-id -p %s SEU_IP_DO_CELULAR\033[0m\n\n' "$PORTA"
    cmd_start
}

cmd_start() {
    pgrep -f sshd >/dev/null 2>&1 && { ok "o sshd já está no ar"; cmd_status; return; }
    sshd && ok "sshd no ar"
    cmd_status
}

cmd_status() {
    ip=$(ip_do_wifi)
    if [ -n "$ip" ]; then
        printf '\n  \033[1m%s\033[0m porta \033[1m%s\033[0m\n' "$ip" "$PORTA"
        printf '  \033[2mno PC:  stylus phone wifi --ssh %s\033[0m\n\n' "$ip"
    else
        warn "sem wifi. o adb por cabo continua funcionando."
    fi
    pgrep -f sshd >/dev/null 2>&1 && ok "sshd rodando" || warn "sshd parado"
}

cmd_scrobbles() {
    # O Pano Scrobbler guarda o histórico num banco do próprio aplicativo, que
    # o Termux não alcança. O que ele ALCANÇA é a exportação: no Pano, em
    # Ajustes → Exportar, salve para /sdcard. Este comando converte o que
    # estiver lá para o formato de uma linha por colocação que o PC lê.
    achou=""
    for f in /sdcard/Download/pano-scrobbler*.json /sdcard/pano*.json \
             /sdcard/Download/scrobbles*.json; do
        [ -r "$f" ] && achou="$f"
    done
    if [ -z "$achou" ]; then
        warn "não achei exportação do Pano em /sdcard."
        printf '  \033[2mno Pano: Ajustes → Exportar → salve em /sdcard\033[0m\n'
        return 1
    fi
    info "Convertendo $achou"
    python - "$achou" "$SAIDA" <<'PYEOF'
import json, sys, time
entrada, saida = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(entrada, encoding="utf-8"))
except Exception as e:
    sys.exit(f"não deu para ler: {e}")
itens = d if isinstance(d, list) else (d.get("scrobbles") or d.get("tracks") or [])
n = 0
with open(saida, "w", encoding="utf-8") as fh:
    for it in itens:
        if not isinstance(it, dict):
            continue
        ts = it.get("timestamp") or it.get("time") or 0
        if ts and ts > 1e11:          # milissegundos
            ts //= 1000
        art = it.get("artist") or ""
        alb = it.get("album") or ""
        if not (ts and art):
            continue
        # A quarta coluna é a PASTA no PC, que o celular não conhece. Fica o
        # par artista/álbum e o PC resolve para a pasta dele.
        fh.write(f"{int(ts)}\t{art}\t{alb}\t\n")
        n += 1
print(f"{n} linhas")
PYEOF
    ok "em $SAIDA — no PC: stylus phone scrobbles"
}

case "${1:-status}" in
    install)   cmd_install ;;
    start)     cmd_start ;;
    status)    cmd_status ;;
    scrobbles) cmd_scrobbles ;;
    *) printf 'stylus-agent: install | start | status | scrobbles\n'; exit 1 ;;
esac
