#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  RECUPERAÇÃO — roda da live USB para desbrickar a máquina
# ═══════════════════════════════════════════════════════════════════════════
#  1. Boota do USB do Stylus (live)
#  2. Abre um terminal
#  3. Roda: bash /run/media/.../recover.sh
#
#  O que faz:
#  - Monta a partição instalada
#  - Volta o SDDM para Session=stylus.desktop (i3)
#  - Reinstala i3 que foi removido
#  - Desliga autologin temporariamente para poder testar
#  - Reboot
# ═══════════════════════════════════════════════════════════════════════════
set -uo pipefail

RED='\033[1;31m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; BLUE='\033[1;34m'; NC='\033[0m'
info()  { printf "${BLUE}==>${NC} %s\n" "$*"; }
ok()    { printf "${GREEN}  ✓${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}  !${NC} %s\n" "$*"; }
fail()  { printf "${RED}  ✗${NC} %s\n" "$*"; }

echo ""
printf "${RED}══════════════════════════════════════════${NC}\n"
printf "${RED}   RECUPERAÇÃO STYLUS${NC}\n"
printf "${RED}══════════════════════════════════════════${NC}\n"
echo ""

# ── 1. Encontrar a partição instalada ─────────────────────────────────
info "Procurando a partição Stylus instalada..."

TARGET=""
for dev in /dev/nvme* /dev/sda /dev/sdb /dev/sdc /dev/sdd /dev/vda /dev/vdb; do
    [[ -b $dev ]] || continue
    for part in "${dev}p2" "${dev}2"; do
        [[ -b $part ]] || continue
        if blkid -o value -s TYPE "$part" 2>/dev/null | grep -q "ext4\|btrfs\|xfs"; then
            if mount -o ro "$part" /mnt 2>/dev/null; then
                if [[ -d /mnt/usr/local/bin ]]; then
                    TARGET="$part"
                    ok "Encontrada: $part montada em /mnt"
                    break 2
                fi
                umount /mnt 2>/dev/null
            fi
        fi
    done
done

# Tentar anche /dev/sda1, /dev/sdb1 etc para live USBs diferentes
if [[ -z $TARGET ]]; then
    for part in /dev/sda1 /dev/sdb1 /dev/sdc1 /dev/sdd1 /dev/nvme0n1p2 /dev/nvme0n1p3; do
        [[ -b $part ]] || continue
        if mount -o ro "$part" /mnt 2>/dev/null; then
            if [[ -d /mnt/usr/local/bin ]]; then
                TARGET="$part"
                ok "Encontrada: $part montada em /mnt"
                break
            fi
            umount /mnt 2>/dev/null
        fi
    done
fi

if [[ -z $TARGET ]]; then
    fail "Não encontrei a partição instalada."
    echo ""
    echo "  Monte manualmente:"
    echo "    lsblk               (para ver os discos)"
    echo "    mount /dev/sdXN /mnt"
    echo "    bash $0"
    echo ""
    exit 1
fi

# ── 2. Montar juga /home e /boot ──────────────────────────────────────
# Descobrir o disco base
DISK="${TARGET%p*}"
[[ $DISK == *p* ]] && DISK="${DISK%p*}"

info "Procurando home e boot..."
for part in "${DISK}p1" "${DISK}1" "${DISK}p3" "${DISK}3"; do
    [[ -b $part ]] || continue
    FSTYPE=$(blkid -o value -s TYPE "$part" 2>/dev/null)
    if [[ $FSTYPE == "vfat" && ! -d /mnt/boot/efi ]]; then
        mkdir -p /mnt/boot/efi
        mount -o ro "$part" /mnt/boot/efi 2>/dev/null && ok "EFI: $part"
    fi
done

# Usar bind para simular chroot
for d in dev proc sys run; do
    mount --bind "/$d" "/mnt/$d" 2>/dev/null
done

# ── 3. Descobrir o usuário ────────────────────────────────────────────
REAL_USER=""
while IFS=: read -r user _ uid _; do
    if [[ $uid -ge 1000 && $uid -lt 65000 ]]; then
        [[ -d "/mnt/home/$user" ]] && REAL_USER="$user" && break
    fi
done < /mnt/etc/passwd

if [[ -z $REAL_USER ]]; then
    fail "Não encontrei usuário com home em /mnt/home/"
    exit 1
fi
ok "Usuário: $REAL_USER"

# ── 4. CORRIGIR SDDM ─────────────────────────────────────────────────
info "Corrigindo SDDM..."
SDDM_CONF="/mnt/etc/sddm.conf.d/stylus.conf"
if [[ -f $SDDM_CONF ]]; then
    # Voltar para stylus.desktop (i3)
    sed -i 's/^Session=.*/Session=stylus.desktop/' "$SDDM_CONF"
    ok "Session=stylus.desktop"
    
    # Desabilitar autologin para poder testar
    sed -i '/^\[Autologin\]/,/^$/s/^User=.*/#User=/' "$SDDM_CONF"
    sed -i '/^\[Autologin\]/,/^$/s/^Session=.*/#Session=/' "$SDDM_CONF"
    ok "Autologin desabilitado (para teste)"
else
    # Criar do zero
    mkdir -p /mnt/etc/sddm.conf.d
    cat > "$SDDM_CONF" <<'SDDM'
[General]
DisplayServer=x11
Numlock=on

[Theme]
Current=stylus

#[Autologin]
#User=TODO
#Session=stylus.desktop
#Relogin=true
SDDM
    ok "SDDM criado do zero"
fi

# ── 5. Modo = music ───────────────────────────────────────────────────
info "Setando modo music..."
MODE="/mnt/home/$REAL_USER/.config/stylus/mode"
mkdir -p "$(dirname "$MODE")"
echo "music" > "$MODE"
chroot /mnt chown "$REAL_USER":"$(id -gn "$REAL_USER" 2>/dev/null || echo "$REAL_USER")" "$MODE" 2>/dev/null || true
ok "Modo: music"

# ── 6. Reinstalar i3 ──────────────────────────────────────────────────
info "Reinstalando i3 (dentro do chroot)..."
I3_PKGS="i3-wm i3lock xss-lock polybar rofi picom dunst feh arandr autorandr"
chroot /mnt pacman -S --needed --noconfirm $I3_PKGS 2>/dev/null && ok "i3 reinstalado" || warn "pode ter falhado — tente manualmente"

# ── 7. Desbloquear o sistema ──────────────────────────────────────────
# Remover lock do pacman se existir
rm -f /mnt/var/lib/pacman/db.lck 2>/dev/null && ok "Lock do pacman removido" || true

# ── 8. Verificar ──────────────────────────────────────────────────────
echo ""
info "Verificando..."
echo "  SDDM Session: $(grep '^Session=' "$SDDM_CONF" 2>/dev/null || grep '^#Session=' "$SDDM_CONF" 2>/dev/null || echo 'NÃO DEFINIDO')"
echo "  Modo: $(cat "$MODE" 2>/dev/null || echo 'ERRO')"
echo "  i3: $(chroot /mnt pacman -Qi i3-wm 2>/dev/null | grep 'Versão' || echo 'NÃO INSTALADO')"

# ── 9. Desmontar ──────────────────────────────────────────────────────
info "Desmontando..."
for d in dev proc sys run boot/efi; do
    umount "/mnt/$d" 2>/dev/null
done
umount /mnt 2>/dev/null

echo ""
printf "${GREEN}═══ PRONTO ═══${NC}\n"
echo ""
echo "  1. Remova o USB"
echo "  2. Reinicie a máquina"
echo "  3. O SDDM vai pedir login (autologin desabilitado para teste)"
echo "  4. Entre como $REAL_USER, senha a que ele usa"
echo "  5. Se i3 funcionar, rode: sudo stylus-switch-kde"
echo "     (dessa vez vai funcionar porque já tem internet)"
echo ""
echo "  Se quiser habilitar autologin de novo depois:"
echo "    sudo nano /etc/sddm.conf.d/stylus.conf"
echo "    Descomente User= e Session= na seção [Autologin]"
echo ""
