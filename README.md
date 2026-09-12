# AI Gateway Infra

Ansible playbook that installs Docker, Langfuse, LiteLLM, and nginx on a single Ubuntu 24.04 VM.

Langfuse and LiteLLM each run from their own published Docker Compose file (re-downloaded on every playbook run). nginx routes `langfuse.test` → Langfuse (:3000) and `litellm.test` → LiteLLM (:4000).

## What you need

- A Ubuntu 24.04 VM reachable over SSH as `root` (key-based auth; no password prompt)
- [uv](https://docs.astral.sh/uv/) on the machine that runs Ansible (your laptop or CI)
- This repository checked out

You only need to provide the VM’s IP address. Default secrets in the repo are fine for a first bring-up.

Need a new DigitalOcean host? Provision one with OpenTofu in [`terraform/`](terraform/) (`s-8vcpu-16gb`, ~$96/mo), then paste the output IP below.

Running on a smaller OCI `VM.Standard.E5.Flex` box? Host-side memory/CPU caps used on one live deploy: [`docs/oci_vm.md`](docs/oci_vm.md).

## Deploy (given a VM IP)

Replace `VM_IP` with the real address (example: `203.0.113.10`).

```bash
# 1. Python deps + Ansible Galaxy roles/collections
uv sync
source .venv/bin/activate
ansible-galaxy install -r requirements.yml

# 2. Point inventory at the VM (only change this one value)
#    File: inventory/hosts.yml
#    Key:  ansible_host
#    Keep ansible_user: root
sed -i.bak "s/ansible_host:.*/ansible_host: VM_IP/" inventory/hosts.yml

# 3. Confirm SSH works before spending time on the playbook
ssh -o BatchMode=yes -o ConnectTimeout=10 root@VM_IP 'echo ok'

# 4. Run the playbook
ansible-playbook site.yml
```

Success looks like: playbook exit code `0`, and the final recap has no `failed=` hosts. First run can take several minutes (Docker install + image pulls). After it finishes, wait ~2–3 minutes for Langfuse migrations before verifying.

## Verify

On the same machine that runs Ansible:

```bash
# Name resolution for the hostname-based nginx routes
echo "VM_IP langfuse.test litellm.test" | sudo tee -a /etc/hosts

# Health endpoints (expect HTTP 200)
curl -si http://langfuse.test/api/public/health | head -1
curl -si http://litellm.test/health/liveliness | head -1

# Optional: confirm Langfuse headless init created the project
curl -su 'pk-lf-local-dev-public-key:sk-lf-local-dev-secret-key' \
  http://langfuse.test/api/public/projects
```

UIs (browser):

| Service | URL | Login |
|---------|-----|-------|
| Langfuse | http://langfuse.test | `local@langfuse.com` / `password` |
| LiteLLM | http://litellm.test/ui | `admin` / `sk-local-dev-master-key` |

Debugging tips (Host-header routing, bypassing nginx, on-VM logs): [`docs/verify.md`](docs/verify.md).  
How nginx hostname routing works: [`docs/nginx_routing.md`](docs/nginx_routing.md).  
OCI VM shape and Docker ceilings (worked example): [`docs/oci_vm.md`](docs/oci_vm.md).

## After deploy

Health checks only prove the stack is up. Two things still need a look, or you will forget them.

### Models and pricing

`site.yml` does not register provider models or their rates. Add a model with the
[`litellm-provision-model`](.cursor/skills/litellm-provision-model/SKILL.md) skill (management API:
`/model/new`, then a real completion).

A completion that returns content can still cost **$0.00** in spend logs. The LiteLLM image's
bundled price map often lags the models you just added. After every new model, do **step 7** of
that skill: read `input_cost_per_token` from `/model/info`, PATCH the rates if they are `0`, and
confirm `x-litellm-response-cost` is non-zero.

### Request/response logging

There is no separate skill for this. The playbook's first run POSTs LiteLLM's `/config/update` to
turn on **Store Prompts in Spend Logs** (30-day retention), which is what fills the Logs page.
Later playbook runs leave whatever an admin already stored.

Confirm it is on (or flip it) with the same API the dashboard uses:

```bash
curl -sS -H "Authorization: Bearer sk-local-dev-master-key" \
  'http://litellm.test/config/list?config_type=general_settings' \
  | jq '.[] | select(.field_name=="store_prompts_in_spend_logs")'

curl -sS -X POST http://litellm.test/config/update \
  -H "Authorization: Bearer sk-local-dev-master-key" \
  -H 'Content-Type: application/json' \
  -d '{"general_settings":{"store_prompts_in_spend_logs":true,"maximum_spend_logs_retention_period":"30d"}}'
```

Or in the UI: http://litellm.test/ui → **Admin Settings → Logging Settings**. If you turn it off
there, later playbook runs leave it off. Only new requests get bodies; older log rows stay empty.

## Optional: change secrets

Only if you want non-default credentials:

- Langfuse: [`roles/langfuse/files/langfuse.env`](roles/langfuse/files/langfuse.env)
- LiteLLM: [`roles/litellm/files/docker-compose.override.yml`](roles/litellm/files/docker-compose.override.yml)

Do not change `LITELLM_SALT_KEY` after you have stored provider API keys in LiteLLM.

## Layout

```
site.yml                 # playbook entrypoint
inventory/hosts.yml      # VM IP + ansible_user
requirements.yml         # Galaxy roles + collections
roles/langfuse/          # download compose + .env + up
roles/litellm/           # download compose + override + up + logging defaults
roles/nginx_gateway/     # hostname vhosts
terraform/               # optional: DigitalOcean droplet (OpenTofu)
docs/verify.md
docs/nginx_routing.md
docs/oci_vm.md
```
