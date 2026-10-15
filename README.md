# PVM Quickstart

This repo uses Ansible playbooks to set up an Ubuntu server for Pagetable-based Virtual Machines (PVM) with CubeSandbox.

Thi repo was created for the blog post "[Giving every agent its own microVM](https://karinja.ai/blog/001-giving-every-agent-its-own-microvm)" by Karinja. The optional benchmark playbook was used in gathering the data for the blog post.

## Requirements

- Clean Ubuntu 24.04+ x86 VPS, with at least 4 CPUs and 32 GiB RAM.
- SSH access as root, or a user with `sudo`.
- One blank data disk >50GB
- [uv](https://docs.astral.sh/uv/getting-started/installation/) and Make.

Note that the hardware requirement is not a limitation, its just what we tested with. Feel free to adjust params in playbooks to fit your machine.

## Set up a server

Clone the repo, then run setup with the server IP:

```sh
git clone <repository-url> cubesandbox-pvm-automation
cd cubesandbox-pvm-automation
make setup VM_IP=203.0.113.10 <- replace
```

The default SSH user is `root`; set `SSH_USER=ubuntu` for another user with sudo. The default data disk is `/dev/vdb`; set `DATA_DEVICE=/dev/sdb` if your server uses another device name. For example:

```sh
make setup VM_IP=203.0.113.10 SSH_USER=ubuntu DATA_DEVICE=/dev/nvme1n1
```

Make sure SSH works and the host has finished its first boot before setup. The playbook pauses Ubuntu update timers during setup and starts them again when it ends. It stops if the data disk has a file system or data signature. Do not use a disk that has data to keep.

The command installs local Ansible tools from `uv.lock`, writes an ignored inventory file, and runs the playbook. The host record is saved at `/root/cubesandbox-automation-result.json`; a local copy is saved under `results/`.

## Optional benchmark

After setup, run:

```sh
make benchmark
```

It runs five warm-up samples and 50 measured samples. Results are saved under `results/`. To touch 128 MiB in each guest before snapshot, run `make benchmark EXTRA_VARS='benchmark_working_set_mib=128'`. The benchmark pauses Ubuntu update timers while it runs.

## Other commands

- `make check` runs Ansible, Python, and YAML checks.
- `make format` formats Python files.
- `make clean-results` removes local benchmark results.

The WebUI listens on localhost port 12088. Open it through SSH:

```sh
ssh -L 12088:127.0.0.1:12088 USER@SERVER_IP
```

Then open <http://127.0.0.1:12088>.

## License

The automation is under the MIT License. CubeSandbox and its downloaded files have their own licenses; see the [CubeSandbox license](https://github.com/TencentCloud/CubeSandbox/blob/f1aaa737fb3862202b1731e0e0d844c28779f930/LICENSE).
