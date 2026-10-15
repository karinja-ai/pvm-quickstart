#!/usr/bin/env bash
set -euo pipefail
mkdir -p /var/log/cubesandbox-automation
exec > >(tee -a /var/log/cubesandbox-automation/cgroup-troubleshooting.log) 2>&1
printf 'Started: '
date -Is
printf 'multipath maps before change:\n'
multipath -ll || true
lsblk -o NAME,TYPE,MAJ:MIN,FSTYPE,MOUNTPOINTS
systemctl disable --now multipathd.service multipathd.socket
if ! grep -qw cpu /sys/fs/cgroup/cgroup.subtree_control; then
  printf '+cpu\n' >/sys/fs/cgroup/cgroup.subtree_control
fi
printf 'controllers: '
cat /sys/fs/cgroup/cgroup.controllers
printf 'enabled: '
cat /sys/fs/cgroup/cgroup.subtree_control
systemctl is-enabled multipathd.service multipathd.socket || true
systemctl is-active multipathd.service multipathd.socket || true
printf 'Finished: '
date -Is
