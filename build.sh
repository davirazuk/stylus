#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  build.sh — constrói a ISO do STYLUS
# ═══════════════════════════════════════════════════════════════════════════
#      ./build.sh              constrói em ./out
#      ./build.sh --clean      joga fora o cache de pacotes antes
#      ./build.sh --no-check   pula as verificações (não faça isso)
#
#  Numa máquina Arch roda o mkarchiso direto. Fora dela, cai para um contêiner
#  podman sem privilégio de root. Nativo é bem mais rápido e não precisa de
#  15 GB a mais para a imagem do contêiner.
#
#  Espere uns 15 GB de espaço temporário e uma primeira execução longa
#  baixando pacotes. As seguintes reaproveitam ./.pkgcache.
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

PROFILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${STYLUS_WORK:-$PROFILE/work}"
OUT="${STYLUS_OUT:-$PROFILE/out}"
CACHE="${STYLUS_CACHE:-$PROFILE/.pkgcache}"

c0=$'\033[0m'; cb=$'\033[1;34m'; cg=$'\033[1;32m'; cr=$'\033[1;31m'; cd=$'\033[2m'
info() { printf '%s==>%s %s\n' "$cb" "$c0" "$*"; }
die()  { printf '%s==> ERRO:%s %s\n' "$cr" "$c0" "$*" >&2; exit 1; }

CHECK=1; CLEAN=0
while [[ $# -gt 0 ]]; do
    case $1 in
        --clean)    CLEAN=1; shift ;;
        --no-check) CHECK=0; shift ;;
        -h|--help)  sed -n '3,10p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) die "não conheço $1" ;;
    esac
done

if (( CHECK )); then
    info "Conferindo o perfil…"
    "$PROFILE/tools/check.sh" || die "conserte o que está acima, ou --no-check."
fi

mkdir -p "$OUT" "$CACHE"
(( CLEAN )) && { info "Jogando fora o cache…"; rm -rf "$CACHE"; mkdir -p "$CACHE"; }

# O mkarchiso deixa pedaços do work pertencendo a uid mapeado; limpar como
# root é a única forma que funciona nos dois caminhos (nativo e contêiner).
limpar_work() {
    [[ -e $WORK ]] || return 0
    info "Limpando o diretório de trabalho anterior…"
    sudo rm -rf "$WORK" 2>/dev/null || rm -rf "$WORK" 2>/dev/null || true
    [[ -e $WORK ]] && die "não consegui remover $WORK"
    return 0
}
limpar_work
mkdir -p "$WORK"

start=$SECONDS
if command -v mkarchiso >/dev/null && [[ -f /etc/arch-release || -f /etc/os-release ]]; then
    info "mkarchiso, nativo (isto demora)…"
    sudo mkarchiso -v -w "$WORK" -o "$OUT" -c "$CACHE" "$PROFILE" \
        || die "o mkarchiso falhou."
elif command -v podman >/dev/null; then
    info "sem mkarchiso aqui; construindo dentro de um contêiner…"
    IMAGE=stylus-builder
    podman image exists "$IMAGE" || \
        podman build -t "$IMAGE" -f "$PROFILE/tools/Containerfile" "$PROFILE/tools"
    podman run --rm --privileged \
        -v "$PROFILE":/profile:z -v "$WORK":/work:z,dev,suid,exec \
        -v "$OUT":/out:z -v "$CACHE":/var/cache/pacman/pkg:z,dev,suid,exec \
        "$IMAGE" mkarchiso -v -w /work -o /out /profile || die "o contêiner falhou."
else
    die "instale o archiso (Arch) ou o podman (qualquer distro)."
fi

elapsed=$(( SECONDS - start ))
iso=$(find "$OUT" -maxdepth 1 -name '*.iso' -printf '%T@ %p\n' | sort -rn | head -1 | cut -d' ' -f2-)
printf '\n%s  STYLUS construído em %dm%02ds%s\n\n' "$cg" $((elapsed/60)) $((elapsed%60)) "$c0"
if [[ -n ${iso:-} ]]; then
    printf '    %s\n    %s\n\n' "$iso" "$(du -h "$iso" | cut -f1)"
    printf '  Gravar num pendrive:\n'
    printf '    %stools/flash.sh %s%s\n\n' "$cd" "$iso" "$c0"
    printf '  Ou experimentar sem gravar nada:\n'
    printf '    %sqemu-system-x86_64 -m 4G -enable-kvm -cdrom %s%s\n\n' "$cd" "$iso" "$c0"
fi
