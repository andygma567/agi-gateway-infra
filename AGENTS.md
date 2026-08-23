# AGENTS.md

Instructions for AI agents operating in this repository.

## Goal

Bring up Langfuse + LiteLLM + nginx on one Ubuntu VM via Ansible. The human usually only supplies a **VM IP**. Follow [`README.md`](README.md) as the runbook.

## Do this

1. Read `README.md` and run the steps in **Deploy (given a VM IP)** in order.
2. Set **only** `ansible_host` in `inventory/hosts.yml` to the provided IP. Leave `ansible_user: root`.
3. Verify SSH first: `ssh -o BatchMode=yes -o ConnectTimeout=10 root@VM_IP 'echo ok'`. If that fails, stop and report — do not run the playbook.
4. Run `ansible-playbook site.yml` from the repo root with the `.venv` activated.
5. After a successful playbook, wait ~2–3 minutes, then run the health curls from the README (with `/etc/hosts` updated, or use `curl -H 'Host: langfuse.test' http://VM_IP/...` if you cannot edit hosts).
6. Report: playbook recap, health check HTTP status codes, and the UI URLs + default logins from the README.

## Do not do this

- Do not create new roles, playbooks, vault files, or CI unless the human asks.
- Do not change Langfuse/LiteLLM secrets unless the human asks.
- Do not change `LITELLM_SALT_KEY` after a successful deploy with stored provider keys.
- Do not pin image versions or vendor compose files; roles intentionally re-download upstream compose on each run.
- Do not use `ansible-lint`, Molecule, or a verify playbook — verification is manual curl/browser checks.
- Do not commit `.venv/`, `.ansible/`, or real production secrets.

## Facts that prevent wrong guesses

- Inventory group is `gateway`; playbook hosts pattern is `gateway`.
- Connection user is `root` (`become: true` is still set; that is expected).
- Langfuse listens on host port **3000**; LiteLLM on **4000**; nginx on **80**.
- Hostnames are `langfuse.test` and `litellm.test` (`.test` is a domain suffix, not a test suite).
- Galaxy install: `ansible-galaxy install -r requirements.yml` (roles land under `.ansible/roles` per `ansible.cfg`).
