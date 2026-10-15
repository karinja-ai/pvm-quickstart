#!/usr/bin/env bash
set -euo pipefail
EXPECTED_KERNEL='6.6.117-opencloudos9.cubesandbox.pvm.host-gbc75224fca7e'
mkdir -p /var/log/cubesandbox-automation
exec > >(tee -a /var/log/cubesandbox-automation/pvm-kernel.log) 2>&1
printf 'Post-reboot verification: '
date -Is
printf 'Boot ID: '
cat /proc/sys/kernel/random/boot_id
printf 'Kernel: '
uname -r
[[ "$(uname -r)" == "$EXPECTED_KERNEL" ]]
modprobe kvm_pvm
lsmod | grep kvm
[[ -e /dev/kvm ]]
ls -l /dev/kvm
printf 'kvm_pvm\n' >/etc/modules-load.d/kvm-pvm.conf
PVM_KVER="$(uname -r)"
GRUB_DEFAULT_LINE="GRUB_DEFAULT=\"Advanced options for Ubuntu>Ubuntu, with Linux ${PVM_KVER}\""
if grep -q '^GRUB_DEFAULT=' /etc/default/grub; then
  sed -i "s|^GRUB_DEFAULT=.*|${GRUB_DEFAULT_LINE}|" /etc/default/grub
else
  printf '%s\n' "$GRUB_DEFAULT_LINE" >>/etc/default/grub
fi
update-grub
grep -F -- "Ubuntu, with Linux ${PVM_KVER}" /boot/grub/grub.cfg
printf 'Default boot: '
grep '^GRUB_DEFAULT=' /etc/default/grub
printf 'Original kernel still installed: '
ORIGINAL_KERNEL="$(cat /root/cubesandbox-automation-original-kernel)"
test -e "/boot/vmlinuz-${ORIGINAL_KERNEL}" && echo yes
printf 'Verified: '
date -Is
