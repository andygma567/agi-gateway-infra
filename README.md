# AI Gateway Infra

Ansible playbook that installs Docker, Langfuse, LiteLLM, and nginx on a single Ubuntu VM.

Langfuse and LiteLLM each run from their own published Docker Compose file (re-downloaded on every playbook run). nginx routes `langfuse.test` → Langfuse and `litellm.test` → LiteLLM.

## Prerequisites

- A Ubuntu 24.04 VM you can SSH into as root
- This repo on your laptop, with a Python 3.11+ venv:

```bash
uv sync
source .venv/bin/activate
ansible-galaxy install -r requirements.yml
```

## Configure

1. Set your VM IP in [`inventory/hosts.yml`](inventory/hosts.yml).
2. (Optional) Change secrets in [`roles/langfuse/files/langfuse.env`](roles/langfuse/files/langfuse.env) and [`roles/litellm/files/docker-compose.override.yml`](roles/litellm/files/docker-compose.override.yml).

## Run

```bash
ansible-playbook site.yml
```

## Verify

See [`docs/verify.md`](docs/verify.md). Short version — on your laptop:

```bash
echo "<VM_IP> langfuse.test litellm.test" | sudo tee -a /etc/hosts
curl -i http://langfuse.test/api/public/health
curl -i http://litellm.test/health/liveliness
open http://langfuse.test
open http://litellm.test/ui
```

How nginx hostname routing works: [`docs/nginx_routing.md`](docs/nginx_routing.md).
