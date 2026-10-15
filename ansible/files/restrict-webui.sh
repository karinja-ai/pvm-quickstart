#!/usr/bin/env bash
set -euo pipefail

root=/usr/local/services/cubetoolbox
compose="$root/webui/docker-compose.yaml"
template="$root/webui/docker-compose.yaml.template"
network=webui_default
test -f "$compose"
test -f "$template"

read -r subnet < <(docker network inspect "$network" \
  --format '{{(index .IPAM.Config 0).Subnet}}')
host_gateway=172.17.0.1
ip -4 addr show dev docker0 | grep -Fq "$host_gateway/"

python3 - "$template" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
text = text.replace(
    '      - "__WEB_UI_HOST_PORT__:80"',
    '      - "127.0.0.1:__WEB_UI_HOST_PORT__:80"',
)
if '127.0.0.1:__WEB_UI_HOST_PORT__:80' not in text:
    raise SystemExit("could not restrict WebUI port to loopback")
path.write_text(text)
PY

python3 - <<'PY'
import re
import subprocess

status = subprocess.check_output(["ufw", "status", "numbered"], text=True)
numbers = [
    int(match.group(1))
    for match in re.finditer(
        r"^\[\s*(\d+)\].*# CubeSandbox WebUI (?:to local CubeOps API|local API)$",
        status,
        re.MULTILINE,
    )
]
for number in sorted(numbers, reverse=True):
    subprocess.run(
        ["ufw", "--force", "delete", str(number)],
        check=True,
        stdout=subprocess.DEVNULL,
    )
PY

ufw allow from "$subnet" to "$host_gateway" port 3010 proto tcp \
  comment 'CubeSandbox WebUI local API'
systemctl reset-failed cube-sandbox-webui.service || true
systemctl restart cube-sandbox-webui.service
for _ in $(seq 1 90); do
  if systemctl is-active --quiet cube-sandbox-webui.service; then
    curl -fsS --max-time 3 http://127.0.0.1:12088/healthz >/dev/null
    ss -lnt | grep -Fq '127.0.0.1:12088'
    echo "WebUI is healthy on 127.0.0.1:12088; local API access is limited to $subnet"
    exit 0
  fi
  sleep 1
done
journalctl -u cube-sandbox-webui.service -n 40 --no-pager >&2
exit 1
