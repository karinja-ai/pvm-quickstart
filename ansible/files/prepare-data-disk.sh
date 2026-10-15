#!/usr/bin/env bash
set -euo pipefail

device="${1:-/dev/vdb}"
mount_point="${2:-/data/cubelet}"

if mountpoint -q "$mount_point"; then
  mounted_source="$(findmnt -n -o SOURCE --target "$mount_point")"
  mounted_type="$(findmnt -n -o FSTYPE --target "$mount_point")"
  [[ "$mounted_type" == xfs ]] || {
    echo "Refusing: $mount_point is not XFS" >&2
    exit 1
  }
  [[ "$(readlink -f "$mounted_source")" == "$(readlink -f "$device")" ]] || {
    echo "Refusing: $mount_point is not mounted from $device" >&2
    exit 1
  }
  xfs_info "$mount_point" | grep -q 'reflink=1' || {
    echo "Refusing: XFS reflink is not enabled on $mount_point" >&2
    exit 1
  }
  echo "$device is already mounted as XFS with reflink at $mount_point"
  exit 0
fi

[[ "$(lsblk -dn -o TYPE "$device" | xargs)" == disk ]] || {
  echo "Refusing: $device is not a whole disk" >&2
  exit 1
}
[[ -z "$(lsblk -nr -o MOUNTPOINT "$device" | xargs)" ]] || {
  echo "Refusing: $device has a mounted child" >&2
  exit 1
}
[[ -z "$(wipefs -n -o TYPE "$device" 2>/dev/null | awk 'NR>1 && NF {print $1}')" ]] || {
  echo "Refusing: $device has a file system or signature" >&2
  exit 1
}

install -d -m 0755 "$(dirname "$mount_point")"
mkfs.xfs -m reflink=1 "$device"
uuid="$(blkid -s UUID -o value "$device")"
install -d -m 0755 "$mount_point"
if ! grep -Fq "UUID=$uuid $mount_point xfs" /etc/fstab; then
  printf 'UUID=%s %s xfs defaults 0 2\n' "$uuid" "$mount_point" >>/etc/fstab
fi
mount "$mount_point"
xfs_info "$mount_point" | grep -q 'reflink=1'
findmnt "$mount_point"
