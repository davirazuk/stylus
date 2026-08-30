#!/usr/bin/env bash
# shellcheck disable=SC2034
#
# STYLUS — a Linux built around listening to records.
#
# The needle is the single point where an object becomes sound. Everything in
# this profile exists to make that point as short and as deliberate as it can
# be: the file plays as it is (no resampling anywhere in the graph), the disc
# is on the screen while it plays, and the collection remembers what you put
# on it.

iso_name="stylus"
iso_label="STYLUS_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="STYLUS <https://github.com/davirazuk/stylus>"
iso_application="STYLUS Live/Install Medium"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="arch"
buildmodes=('iso')
# Os nomes granulares (bios.syslinux.mbr, uefi-x64.systemd-boot.esp…) são de
# um archiso mais novo do que o que está nos repositórios; o de hoje (89) só
# conhece estes dois, e usar os outros faz a construção morrer na primeira
# linha. Estes cobrem BIOS e UEFI do mesmo jeito.
bootmodes=('bios.syslinux'
           'uefi.systemd-boot')
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
# zstd -19 instead of xz: the ISO comes out within a few percent of the same
# size and decompresses roughly four times faster, which is the difference
# between a live session that feels like a real machine and one that feels
# like a demo. A music OS gets judged on whether the first record you put on
# stutters.
airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' '19' '-b' '1M')
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')

# Modes are re-applied after airootfs is copied in. A trailing slash means
# "recursively". This is what keeps the scripts executable and sudoers at 0440
# even when the profile travels as a zip, which strips every mode.
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/etc/gshadow"]="0:0:400"
  ["/etc/sudoers.d"]="0:0:750"
  ["/etc/sudoers.d/10-stylus-live"]="0:0:440"
  ["/root"]="0:0:750"
  ["/root/.automated_script.sh"]="0:0:755"
  ["/root/.gnupg"]="0:0:700"
  ["/usr/local/bin/"]="0:0:755"
  ["/usr/share/stylus/tools/"]="0:0:755"
  ["/usr/share/stylus/lib/"]="0:0:755"
  ["/usr/share/stylus/first-run.sh"]="0:0:755"
  ["/usr/share/stylus/branding-sync.sh"]="0:0:755"
  ["/etc/skel/.xinitrc"]="0:0:755"
  ["/etc/skel/.config/polybar/launch.sh"]="0:0:755"
  ["/etc/skel/.config/polybar/scripts/"]="0:0:755"
  ["/etc/skel/.config/picom/launch.sh"]="0:0:755"
  ["/etc/skel/.config/i3/scripts/"]="0:0:755"
  ["/etc/skel/.config/rofi/"]="0:0:755"
)
