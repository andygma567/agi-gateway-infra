# Architecture Decision Records

ADRs record durable, cross-cutting architecture decisions so later agents and humans can see *why* something is the way it is.

Routine implementation choices do not need an ADR. Write one when a change locks in a design that later work should not silently undo.

## When to write one

Write an ADR in the same PR as the change when you:

- Choose a stack, layout, or operational model that later PRs should follow
- Reject an approach (and want that rejection to stick)
- Change an earlier accepted decision (that is a new ADR; see below)

Skip an ADR for local refactors, one-off fixes, and copy or docs-only edits.

## File naming

`NNNN-slug.md`, zero-padded, next unused number. Copy [TEMPLATE.md](TEMPLATE.md).

## Status

| Status | Meaning |
| --- | --- |
| `proposed` | Written, not yet the accepted direction |
| `accepted` | Current decision; do not rewrite its rationale |
| `superseded` | Replaced by a later ADR; keep the original text |
| `deprecated` | No longer in force, with no replacement ADR |

Do not rewrite an accepted ADR's decision or rationale. A change of mind is a new ADR. The old ADR may only change status and gain a supersession link.

## Index

None yet. Add a row here when the first ADR lands.
