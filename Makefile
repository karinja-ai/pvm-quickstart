SHELL := /bin/sh
ANSIBLE_DIR := ansible
YAML_FILES := $(wildcard $(ANSIBLE_DIR)/*.yml $(ANSIBLE_DIR)/group_vars/*.yml)
UV ?= uv
SSH_USER ?= root
DATA_DEVICE ?= /dev/vdb
EXTRA_VARS ?=

.PHONY: install setup benchmark check format clean-results

install:
	command -v $(UV) >/dev/null || { echo 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' >&2; exit 2; }
	$(UV) sync --locked

setup: install
	@test -n "$(VM_IP)" || { echo 'Set VM_IP, for example: make setup VM_IP=203.0.113.10' >&2; exit 2; }
	@printf '[cube_hosts]\ncube-host ansible_host=%s ansible_user=%s\n' '$(VM_IP)' '$(SSH_USER)' > $(ANSIBLE_DIR)/inventory.ini
	cd $(ANSIBLE_DIR) && $(UV) run --project .. --locked ansible-playbook site.yml -e cube_data_device=$(DATA_DEVICE)

benchmark: install
	@test -f $(ANSIBLE_DIR)/inventory.ini || { echo 'Run make setup VM_IP=<address> first' >&2; exit 2; }
	cd $(ANSIBLE_DIR) && $(UV) run --project .. --locked ansible-playbook benchmark.yml $(if $(EXTRA_VARS),-e '$(EXTRA_VARS)')

check: install
	cd $(ANSIBLE_DIR) && $(UV) run --project .. --locked ansible-lint --offline site.yml benchmark.yml
	$(UV) run --locked ruff check $(ANSIBLE_DIR)/files/*.py
	$(UV) run --locked ruff format --check $(ANSIBLE_DIR)/files/*.py
	$(UV) run --locked yamllint -c .yamllint $(YAML_FILES)
	cd $(ANSIBLE_DIR) && $(UV) run --project .. --locked ansible-playbook -i inventory.ini.example site.yml --syntax-check
	cd $(ANSIBLE_DIR) && $(UV) run --project .. --locked ansible-playbook -i inventory.ini.example benchmark.yml --syntax-check

format: install
	$(UV) run --locked ruff format $(ANSIBLE_DIR)/files/*.py

clean-results:
	rm -rf results
