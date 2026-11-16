# systematic-restructure

A skill for restructuring a whole codebase on purpose: measure it with a program, design one small spine of shared contracts, map every part onto it, settle the open questions with the owner, prove it on one slice, migrate in measured mechanical batches, then lock it with shrink-only rule checks.

- Method: [`SKILL.md`](SKILL.md). Language-agnostic; for Go modules the inventory step uses [`../code-inventory/code-inventory`](../code-inventory/SKILL.md).
- Templates in [`templates/`](templates/): `discussion.md`, `spine.md`, `mapping.tsv`, `decisions.md`, `run-plan.md`. Copy them into a working folder outside the target repo and fill them in.

Use it by telling the assistant: "Read ~/hub/ai/utils/systematic-restructure/SKILL.md and use it to restructure [the codebase] toward [the goal]."
