# Docs

How-tos, runbooks, and operational notes live here. Architecture Decision Records (ADRs) live in [`decisions/`](decisions/).

Read the docs that apply to the area you are changing before editing it. If a change makes a durable, cross-cutting architecture decision, add an ADR — see [decisions/README.md](decisions/README.md).

## How-tos

| Doc | What it covers |
| --- | --- |
| [nginx_routing.md](nginx_routing.md) | How nginx routes `langfuse.test` and `litellm.test` by Host header |
| [verify.md](verify.md) | Post-deploy health checks, Host-header routing, on-VM logs |
| [oci_vm.md](oci_vm.md) | Host-side memory/CPU caps used on one live OCI deploy |

Bring-up and inventory live in the root [README.md](../README.md), not here.
