#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  tools/flash.sh — grava a ISO num pendrive
# ═══════════════════════════════════════════════════════════════════════════
#      tools/flash.sh out/stylus-2026.08.22-x86_64.iso
#      tools/flash.sh ISO /dev/sdX          se souber o dispositivo
#
#  ISTO APAGA O DISPOSITIVO INTEIRO. Não tem desfazer.
#
#  Por isso o roteiro se recusa a escrever em qualquer coisa que não seja
#  removível, mostra o que vai apagar e espera você digitar o nome do
#  dispositivo. `dd if=... of=/dev/sda` digitado com pressa já apagou o
#  sistema de muita gente, e a única defesa que funciona é a máquina se
#  recusar, não o cuidado da pessoa.
# ═══════════════════════════════════════════════════════════════════════════
set -uo pipefail

c0=$'\033[0m'; cb=$'\033[1;34m'; cg=$'\033[1;32m'; cr=$'\033[1;31m'
cy=$'\033[1;33m'; cd=$'\033[2m'
die() { printf '%s==> ERRO:%s %s\n' "$cr" "$c0" "$*" >&2; exit 1; }

ISO=${1:-}
DEV=${2:-}
[[ -n $ISO ]] || die "diga qual ISO. tools/flash.sh out/stylus-*.iso"
[[ -f $ISO ]] || die "não existe: $ISO"

# ── candidatos: só o que é removível ───────────────────────────────────────
mapfile -t CAND < <(lsblk -dnpo NAME,SIZE,MODEL,RM,TRAN | awk '$4==1 || $5=="usb"')
if [[ -z $DEV ]]; then
    if (( ${#CAND[@]} == 0 )); then
        printf '\n  %snenhum dispositivo removível conectado.%s\n' "$cy" "$c0"
        printf '  %splugue o pendrive e rode de novo.%s\n\n' "$cd" "$c0"
        exit 1
    fi
    printf '\n  %sremovíveis conectados:%s\n\n' "$cb" "$c0"
    for l in "${CAND[@]}"; do printf '    %s\n' "$l"; done
    printf '\n  %stools/flash.sh %s /dev/sdX%s\n\n' "$cd" "$ISO" "$c0"
    exit 0
fi

[[ -b $DEV ]] || die "$DEV não é um dispositivo de bloco."

# ── as travas ──────────────────────────────────────────────────────────────
NOME=$(basename "$DEV")
RM=$(cat "/sys/block/$NOME/removable" 2>/dev/null || echo 0)
TRAN=$(lsblk -dno TRAN "$DEV" 2>/dev/null || echo "")
if [[ $RM != 1 && $TRAN != usb ]]; then
    die "$DEV não é removível nem USB. Recuso.
       Se você tem MESMO certeza, use o dd na mão — mas leia duas vezes."
fi
# O disco onde a raiz está montada nunca, em hipótese alguma.
RAIZ=$(findmnt -no SOURCE / | sed 's/[0-9]*$//;s|/dev/||;s/p$//')
[[ $NOME == "$RAIZ"* ]] && die "$DEV é o disco onde este sistema está rodando."

TAM=$(lsblk -dno SIZE "$DEV")
MODELO=$(lsblk -dno MODEL "$DEV")
printf '\n  %sVAI APAGAR TUDO EM:%s\n\n' "$cr" "$c0"
printf '    %s   %s   %s\n' "$DEV" "$TAM" "${MODELO:-sem modelo}"
printf '\n  %so que tem aí agora:%s\n' "$cd" "$c0"
lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT "$DEV" | sed 's/^/    /'
printf '\n  %sgravando:%s %s (%s)\n' "$cd" "$c0" "$(basename "$ISO")" "$(du -h "$ISO" | cut -f1)"
printf '\n  %sdigite o nome do dispositivo para confirmar (%s), ou qualquer outra coisa para desistir:%s\n  > ' \
    "$cy" "$DEV" "$c0"
read -r resposta
[[ $resposta == "$DEV" ]] || { printf '\n  desisti.\n\n'; exit 1; }

# Desmontar o que estiver montado dele, senão o dd escreve por baixo de um
# sistema de arquivos montado e o resultado é lixo nas duas pontas.
for p in $(lsblk -lnpo NAME "$DEV" | tail -n +2); do
    mountpoint -q "$(findmnt -no TARGET "$p" 2>/dev/null || echo /nada)" && \
        sudo umount "$p" 2>/dev/null || true
done

printf '\n%s==>%s gravando…\n' "$cb" "$c0"
sudo dd if="$ISO" of="$DEV" bs=4M status=progress conv=fsync oflag=direct \
    || die "o dd falhou."
sync
printf '\n%s  pronto.%s\n' "$cg" "$c0"
printf '  %spode tirar. dá boot em UEFI e em BIOS.%s\n\n' "$cd" "$c0"
