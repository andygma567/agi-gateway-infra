# AGENTS.md

General guidance for AI agents working in this repository.

This is a small Ansible project. It is deliberately plain: no Jinja templating, no generated config, no vault, no lint gates. Keep it that way.

## Make minimal changes

Prefer the smallest edit that solves the problem. Don't refactor code you weren't asked to touch, don't add abstraction for something used once, and don't introduce tooling (linters, CI, test harnesses, secret managers) unless asked. If you spot an unrelated problem, mention it instead of fixing it.

## Optimize for understanding

Someone should be able to read a file top to bottom and know what it does without tracing indirection. A static config file you can read beats a template with loops and variables. Literal values beat variables that exist only to be substituted once. When a project has its own documented setup, follow that instead of inventing a local convention, so the docs stay a useful reference.

Prefer boring and obvious over clever and short.

## Keep it easy to change

Give each file one job and keep it short enough to read in one screen. Avoid coupling that forces someone to edit two files to make one change, unless splitting them buys real clarity. Name things so the next reader doesn't need a glossary.

## Think before coding

State your assumptions, and ask when a request has more than one reasonable interpretation rather than silently picking. If a simpler approach exists than the one requested, say so. If you're adding complexity, explain what it buys.

## Deploying

For bringing up a VM, use the `deploy-gateway-vm` skill in `.cursor/skills/`. `README.md` is the runbook.
