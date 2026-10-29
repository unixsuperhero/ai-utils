# Claude Code agents for o-family work

Two custom agent types for coordinating o-family work (ochazuke, oden, matomeru/mtm, nabe, the o-* tools). Each carries the fixed rules that used to be pasted into every brief, so a coordinator's brief only needs the task.

| Agent | Model | Tools | Use for |
|---|---|---|---|
| [`ofam-lane`](ofam-lane.md) | opus | all | One implementation lane: a feature, fix, test, refactor or docs regeneration in a family repo. Works in its own worktree, commits on the lane branch, never merges, pushes, tags or installs, and returns a fixed-format report. |
| [`ofam-planner`](ofam-planner.md) | opus | Read, Grep, Glob, Bash (read-only by prompt), Write/Edit (only under `~/hub/o-plans/` by prompt) | Designs and plans: investigates code read-only with file:line evidence, writes `~/hub/o-plans/plans/<topic>.md` in the family layout with a numbered "Owner questions" section that `mgmt/inventories/owner_questions.py` scans. Never commits. |

The rules come from `~/hub/AGENTS.md` (family rules), `~/hub/ai/instructions/AGENTS.md` (global rules), ochazuke's `AGENTS.md` (invariants) and the coordinator's memory notes. When one of those changes, update the prompts here.

A brief to `ofam-lane` still names the repo, lane name and base, the task, what "done" means, and the exact commit trailer lines. A brief to `ofam-planner` names the plan(s) and code to read and the question to answer.

## Install

Install at user level so the agents load in sessions started in any folder:

```sh
ln -sfn ~/hub/ai/utils/agents/ofam-lane.md    ~/.claude/agents/ofam-lane.md
ln -sfn ~/hub/ai/utils/agents/ofam-planner.md ~/.claude/agents/ofam-planner.md
```

Start a new Claude Code session after installing or editing them.

## Codex

Codex has no equivalent of Claude's per-agent definitions with a tool allowlist loaded from `~/.claude/agents/`. The closest parity would be a Codex profile or prompt file per agent carrying the same text (without the frontmatter) that a coordinator passes to `codex exec`; tool limits would then rest on the prompt and the sandbox mode (`read-only` for the planner, with `~/hub/o-plans` as the only writable root). Not built.
