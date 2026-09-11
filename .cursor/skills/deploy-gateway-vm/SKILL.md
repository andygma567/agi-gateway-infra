---
name: deploy-gateway-vm
description: Deploys Langfuse, LiteLLM, and nginx onto a single Ubuntu VM using this repository's Ansible playbook. Use when the user supplies a VM IP and asks to deploy, provision, re-run, or verify the gateway, or when debugging site.yml, the inventory, or the Langfuse and LiteLLM health endpoints.
---

# Deploy the gateway VM

Bring up Langfuse + LiteLLM + nginx on one Ubuntu VM via Ansible. The human usually supplies only a **VM IP**. `README.md` at the repo root is the runbook; this skill is the operating procedure around it.

## Steps

Run from the repo root. Replace `VM_IP` with the address the human gave you.

1. **Install dependencies.**

   ```bash
   uv sync
   source .venv/bin/activate
   ansible-galaxy install -r requirements.yml
   ```

2. **Point the inventory at the VM.** Set **only** `ansible_host` in `inventory/hosts.yml`. Leave `ansible_user: root` alone.

3. **Verify SSH before anything else.**

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 root@VM_IP 'echo ok'
   ```

   If this fails, stop and report. Do not run the playbook.

4. **Run the playbook.**

   ```bash
   ansible-playbook site.yml
   ```

   Success is exit code `0` and a recap with no `failed=` hosts. First run takes several minutes for the Docker install and image pulls.

5. **Wait ~2-3 minutes** for Langfuse migrations, then check health. If you cannot edit `/etc/hosts`, set the `Host` header by hand instead, which is what nginx routes on:

   ```bash
   curl -si -H 'Host: langfuse.test' http://VM_IP/api/public/health | head -1
   curl -si -H 'Host: litellm.test'  http://VM_IP/health/liveliness | head -1
   ```

6. **Report** the playbook recap, the health check status codes, and the UI URLs plus default logins from `README.md`.

7. **After deploy is not optional.** Health 200s do not mean models or spend tracking are right. Follow **After deploy** in `README.md`: add/check models and rates with the `litellm-provision-model` skill (especially step 7 if spend is `$0`), and confirm LiteLLM is storing request/response bodies (`store_prompts_in_spend_logs`). There is no separate logging skill; the playbook's first run turns it on via `/config/update`.

## Do not

- Create new roles, playbooks, vault files, or CI unless asked.
- Change Langfuse or LiteLLM secrets unless asked.
- Change `LITELLM_SALT_KEY` after a successful deploy with stored provider keys. It encrypts them and they become unreadable.
- Pin image versions or vendor the compose files. The roles re-download upstream compose on every run on purpose, so that upstream changes surface.
- Add `ansible-lint`, Molecule, or a verify playbook. Verification is manual curl and browser checks.
- Commit `.venv/`, `.ansible/`, or real production secrets.

## Facts that prevent wrong guesses

- Inventory group is `gateway`; the playbook's hosts pattern is `gateway`.
- Connection user is `root`. `become: true` is still set in `site.yml`; that is expected and harmless.
- Langfuse listens on host port **3000**, LiteLLM on **4000**, nginx on **80**.
- Hostnames are `langfuse.test` and `litellm.test`. `.test` is a domain suffix like `.com`, not a test suite.
- Galaxy roles install under `.ansible/roles` per `ansible.cfg`.

## When something is broken

To tell whether the problem is nginx or the app, bypass nginx and hit the app port directly:

```bash
curl -si http://VM_IP:3000/api/public/health | head -1
curl -si http://VM_IP:4000/health/liveliness | head -1
```

If the direct port works and the hostname does not, the fault is in nginx. `docs/verify.md` has the on-VM commands (`docker compose ps`, `docker compose logs`, `nginx -t`) and `docs/nginx_routing.md` explains the Host-header routing.
