# OCI VM resource settings (worked example)

These limits were applied on the live OCI VM `meridiangateway` after deploy. This repository’s playbook does **not** install them.

Re-running `ansible-playbook site.yml`:

- **Does** copy [`roles/litellm/files/docker-compose.override.yml`](../roles/litellm/files/docker-compose.override.yml) onto `/opt/litellm/docker-compose.override.yml`. Any LiteLLM memory/CPU/`NUM_WORKERS` tweaks on the VM are overwritten unless you re-apply them after the play.

The live files on the VM are the copy to reuse. This note records shape and ceilings only; it does not reconstruct the full override YAML.

Without Langfuse (~7 GiB of Docker maxima), LiteLLM + its DB (~4.5 GiB) fit a smaller host than this 12 GB box.

## Host

| Item | Value |
|------|-------|
| Hostname | `meridiangateway` |
| Cloud | Oracle Cloud Infrastructure |
| Region / AD | `us-chicago-1` (ORD), availability domain `US-CHICAGO-1-AD-1`, fault domain 3 |
| Display name | `instance-20260821-1757` |
| Shape | `VM.Standard.E5.Flex` |
| Created | 2026-08-21 |
| Hypervisor | KVM / QEMU |
| OS | Ubuntu 24.04.4 LTS, kernel `6.17.0-1020-oracle` |
| Arch | x86_64 |

## CPU

- **1 OCPU** in OCI (`shapeConfig.ocpus: 1.0`)
- Linux sees **2 CPUs** (1 core, 2 threads) — normal for OCI E5: 1 OCPU ≈ 2 vCPUs
- Model: AMD EPYC 9J14 (guest)
- Networking bandwidth: 1 Gbps

## Memory

- **12 GB** billed (`shapeConfig.memoryInGBs: 12.0`)
- OS **MemTotal: 12240836 kB ≈ 11.67 GiB**
- **Swap: none** (`SwapTotal: 0`)

## Storage

- One boot volume: OCI BlockVolume, **46.6 GB** (`sda`)
- Root: `/dev/sda1` ext4, **45 G**, about **19 G used / 26 G avail (44%)** at snapshot time
- `/boot` 881M, `/boot/efi` 105M
- Docker data lives on that same root disk (overlay + volumes)

## Other processes on the host (not Docker-capped)

- **nginx** 1.31.4, active, ~3 workers, **~22 MiB RSS** — reverse proxy; not memory-limited
- OCI unified-monitoring-agent, docker/containerd, sshd

## Where the limits live

Compose override:

- `/opt/litellm/docker-compose.override.yml`

## Docker ceilings

Limits are **maxima**, not reservations.

| Container | mem_limit | CPU quota |
|-----------|-----------|-----------|
| **litellm** | **4g** | **1.0 CPU**, `NUM_WORKERS=1` |
| litellm postgres | 512m | none |

LiteLLM + its DB ≈ **4.5 GiB**. Host ≈ **11.7 GiB** with no swap. nginx is negligible.

## Observed usage (snapshot)

Rough live usage at collection time:

| Container | Usage / limit |
|-----------|----------------|
| LiteLLM | 912 MiB / 4 GiB |
