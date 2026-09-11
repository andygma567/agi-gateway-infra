# DigitalOcean VM (OpenTofu)

Provisions a DigitalOcean Basic droplet for this repo’s Ansible gateway stack
(Langfuse + LiteLLM + nginx). OpenTofu creates the VM and network only; run
[`site.yml`](../site.yml) afterward to install the software.

Compatible with Terraform as well; this README uses `tofu`.

## Spec

| Field | Value |
|-------|--------|
| Size | `s-8vcpu-16gb` (8 shared vCPU, 16 GiB RAM, 320 GiB SSD) |
| OS | Ubuntu 24.04 (`ubuntu-24-04-x64`) |
| Region default | `nyc3` |
| Cost | **~$96/mo** ($0.14286/hr), monthly cap |
| VPC | Created in the chosen region |
| Firewall inbound | TCP 22, 80, 3000, 4000 |
| Backups / DO monitoring | Off |

Cloud-init only creates `/mnt/experiments` on the local SSD. Docker is installed by Ansible (`geerlingguy.docker`), not here.

## Prerequisites

1. [OpenTofu](https://opentofu.org/docs/intro/install/) `>= 1.6`
2. A DigitalOcean personal access token with write access
3. An SSH public key locally (default `~/.ssh/id_ed25519.pub`)

```bash
export DIGITALOCEAN_TOKEN=dop_v1_...
```

Do not put the token in any file in this directory.

## Apply

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # optional overrides (region, name, key path)
tofu init
tofu apply
```

State is local (`terraform.tfstate`). No remote backend.

## Hand off to Ansible

```bash
tofu output -raw ipv4_address
```

From the repo root, put that IP in [`inventory/hosts.yml`](../inventory/hosts.yml) as `ansible_host`, confirm SSH, then follow the root [README](../README.md) deploy steps (`uv sync`, `ansible-galaxy`, `ansible-playbook site.yml`).

Gateway software lands under `/opt/langfuse` and `/opt/litellm`. Experiment data can use `/mnt/experiments` on the 320 GiB disk.

## Destroy

```bash
cd terraform
tofu destroy
```

That deletes the droplet, firewall, VPC, and the SSH key resource registered by this stack. Local Ansible inventory is unchanged — clear `ansible_host` yourself if you reuse the file.
