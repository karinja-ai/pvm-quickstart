#!/usr/bin/env bash
set -euo pipefail
DEB="${1:-/root/linux-image-pvm.deb}"
GRUB_SCRIPT="${2:-/root/host_grub_config.sh}"
EXPECTED_SHA256="821f260869b96e875505b7c947fa5deffbf5daf95cb36751314a1e04c9906da6"

mkdir -p /var/log/cubesandbox-automation
exec > >(tee -a /var/log/cubesandbox-automation/pvm-kernel.log) 2>&1
printf 'Started: '
date -Is
printf 'Current kernel: '
uname -r
sha256sum "$DEB"
echo "$EXPECTED_SHA256  $DEB" | sha256sum --check --status
cp -a /etc/default/grub /root/cubesandbox-automation-grub.default.before
uname -r >/root/cubesandbox-automation-original-kernel

dpkg -i "$DEB"
bash -n "$GRUB_SCRIPT"
bash "$GRUB_SCRIPT"
PVM_IMAGE="$(find /boot -maxdepth 1 -type f -name 'vmlinuz-*opencloudos9.cubesandbox.pvm.host*' -print | sort | tail -n 1)"
[[ -n "$PVM_IMAGE" ]] || {
  echo 'PVM kernel image was not found' >&2
  exit 1
}
PVM_KVER="${PVM_IMAGE##*/vmlinuz-}"
GRUB_ENTRY="Advanced options for Ubuntu>Ubuntu, with Linux ${PVM_KVER}"
grep -F -- "Ubuntu, with Linux ${PVM_KVER}" /boot/grub/grub.cfg
grub-reboot "$GRUB_ENTRY"
grub-editenv /boot/grub/grubenv list
printf 'PVM kernel installed: %s\nOne-time GRUB entry: %s\n' "$PVM_KVER" "$GRUB_ENTRY"
printf 'Finished: '
date -Is
