# o-family agents: Claude, Codex and omp

Use Sol (`gpt-6.1-sol`, high reasoning) for implementation and planning when possible. Claude definitions remain available for read-only broker work or when Sol's sandbox cannot do a lane; say why when choosing Claude.

| Role | Claude | Codex CLI (Sol) | omp (Sol) |
|---|---|---|---|
| Implementation lane | [ofam-lane.md](ofam-lane.md) | [lane.md](../prompts/sol/lane.md), rendered with a brief | [omp/ofam-lane.md](omp/ofam-lane.md) |
| Plan/design | [ofam-planner.md](ofam-planner.md) | [planner.md](../prompts/sol/planner.md), task appended | [omp/ofam-planner.md](omp/ofam-planner.md) |
| UX review | `~/hub/ai/agents/ux-reviewer.md` | [ux-review.md](../prompts/sol/ux-review.md), change appended | [omp/ux-reviewer.md](omp/ux-reviewer.md) |
| UX application | `~/hub/ai/agents/ux-applier.md` | `lane.md` with a punch list as the task | [omp/ux-applier.md](omp/ux-applier.md) |

A lane brief supplies the repo, base, lane/worktree, task, reuse, done-when and exact commit trailers. The worker reuses a supplied worktree, commits only on its branch, and never merges, pushes, tags or installs. It runs targeted checks; the coordinator owns one full gate per batch. A planner investigates read-only, writes only `~/hub/o-plans/`, preserves owner decisions and numbered questions, and never commits. UX roles preserve the full review/applier checklist; harness wrappers keep builds and frames in scratch and narrow applier checks to the lane's targeted policy unless the brief asks for more.

## Shared rules and checks

`agents/ofam-lane.md` and `agents/ofam-planner.md` are the canonical role rules inside named `agent-sync` blocks. [rules/workflow.md](rules/workflow.md) holds shared global workflow rules. [rules/ux-review.md](rules/ux-review.md) and [rules/ux-apply.md](rules/ux-apply.md) are reviewed snapshots from the external Claude UX definitions; those external files are not modified here. Codex/omp files carry checked copies so the harness needs no include support. Codex placeholders, launch/workspace mechanics and coordinator gate recipes stay outside shared blocks.

From this repository:

```sh
python3 -I scripts/agent-sync-check.py             # read-only, portable, no dependencies
python3 -I scripts/agent-sync-check.py --upstream  # also verify the reviewed external sources
python3 -I scripts/agent-sync-check.py --write     # refresh copies after editing canonical rules
```

The check fails for missing/duplicate/empty blocks, unequal copies, stale Sol model ids, or changed omp model/thinking pins. `--write` only changes marked blocks in this repository; it never installs anything. The optional upstream check compares SHA-256 fingerprints in [rules/upstreams.json](rules/upstreams.json) for `~/hub/AGENTS.md`, `~/hub/ai/instructions/AGENTS.md` and both external Claude UX agents. Reconcile changed upstream rules before updating their reviewed fingerprints. This detects updates outside the repo without making the portable check depend on one person's home directory. Harness-specific instructions outside marked blocks still need review.

## Install (owner/coordinator only; not run by a lane)

Run after these files are merged into `~/hub/ai/utils`. These commands create or replace the named symlinks, not config.yml settings. Start a new harness session afterward.

Claude:

```sh
AI_UTILS="$HOME/hub/ai/utils"
mkdir -p "$HOME/.claude/agents"
for agent in ofam-lane ofam-planner; do
  ln -sfn "$AI_UTILS/agents/$agent.md" "$HOME/.claude/agents/$agent.md"
done
for agent in ux-reviewer ux-applier; do
  ln -sfn "$HOME/hub/ai/agents/$agent.md" "$HOME/.claude/agents/$agent.md"
done
```

Codex custom prompts (when supported by the installed CLI):

```sh
AI_UTILS="$HOME/hub/ai/utils"
mkdir -p "$HOME/.codex/prompts"
for prompt in coordinator planner research ux-review vhs; do
  ln -sfn "$AI_UTILS/prompts/sol/$prompt.md" "$HOME/.codex/prompts/ofam-$prompt.md"
done
```

Codex does not load Claude/omp agent definitions. Use `/prompts:ofam-planner` or `/prompts:ofam-ux-review` with the task. `lane.md` uses `{{KEY}}` placeholders, so it must be rendered for each brief rather than installed as an unfilled custom prompt. For an existing lane and filled brief:

```sh
AI_UTILS="$HOME/hub/ai/utils"
LANE=example-lane
REPO="$HOME/proj/example-repo"
SCRATCH="/tmp/$LANE"
mkdir -p "$SCRATCH"
python3 -I "$AI_UTILS/prompts/sol/render.py" "$AI_UTILS/prompts/sol/lane.md" \
  "$SCRATCH/brief.md" > "$SCRATCH/prompt.md"
codex -m gpt-6.1-sol -c model_reasoning_effort=high -s workspace-write -a on-request \
  --add-dir "$REPO/.git" --add-dir "$HOME/.cache/go-build" --add-dir "$HOME/.cache/go-tmp" \
  --add-dir "$HOME/go/pkg/mod" --add-dir "$SCRATCH" \
  -C "$REPO/.worktrees/$LANE" "$(cat "$SCRATCH/prompt.md")"
```

Use the coordinator's own tuios pane per interactive lane and watch with `~/hub/tools/sol-lane/watch.py`; do not inherit the broker's pane identifiers. See [Sol launch mechanics](../prompts/sol/README.md) for the non-interactive fallback and template sections. `~/.codex/config.toml` currently selects `gpt-6.1-sol` with medium reasoning; these launch examples explicitly request high, matching `sol-lane`.

omp:

```sh
AI_UTILS="$HOME/hub/ai/utils"
mkdir -p "$HOME/.omp/agent/agents"
for agent in ofam-lane ofam-planner ux-reviewer ux-applier; do
  ln -sfn "$AI_UTILS/agents/omp/$agent.md" "$HOME/.omp/agent/agents/$agent.md"
done
```

A project-local alternative uses `.omp/agents/` under that project's root. Project definitions override user definitions with the same name. Named profiles load user agents from `~/.omp/profiles/<profile>/agent/agents/`. In this installed loader, `PI_CODING_AGENT_DIR` alone does not redirect task-agent discovery (`src/config.ts:84-87` uses the home-relative config/profile directory); install into the profile's agent folder when using one. In an omp session, ask the coordinator to use the named `ofam-planner` or `ofam-lane` agent through `task`; the task must supply the lane's worktree and scratch paths. Do not request omp's automatic merge-back isolation: these workers leave commits in the assigned worktree for broker review. `spawns: []` and explicit tool allowlists disable nested agent work; shell restrictions and planner write locations remain prompt-enforced, not an OS sandbox.

Each omp file declares `model: openai-codex/gpt-6.1-sol`, `thinkingLevel: high`, and `prewalk: false`. These are per-agent defaults, not an unconditional runtime lock: exact-name `task.agentModelOverrides` entries can override them, and omp can fall back to the parent's model when credentials are unavailable. The inspected config's override is only for the agent named `task`; it does not override these custom names. Its `modelRoles.task` also does not replace their explicit model selectors. Verify the resolved model in omp when running real work; no model inference was performed by this sync lane.

## omp loading evidence (installed v18.14.2, inspected 2026-11-01)

`omp --help` advertises `agents unpack`; `omp agents --help` gives the user destination `~/.omp/agent/agents` and project destination `.omp/agents`. No unpack or install was run.

The installed primary source is `~/.bun/install/global/node_modules/@oh-my-pi/pi-coding-agent/`:

- `src/task/discovery.ts:4-19` documents the native roots and YAML Markdown format, and excludes direct `.claude/agents` imports. Lines 54-66 load `.md` files and symlinks through `parseAgent`. Lines 93-111 select native user/project roots; project wins by name (lines 157-167).
- `src/discovery/helpers.ts:317-375` requires `name`/`description`, parses tool allowlists and `spawns`, and accepts `thinkingLevel` (also `thinking`). Line 376 parses `model`. The bundled reviewer at `src/prompts/agents/reviewer.md` demonstrates the format; the generic task definition at `src/task/agents.ts:53-57` uses per-agent model/thinking defaults.
- `src/task/structured-subagent.ts:416-445` looks up the settings override by exact agent name and passes it alongside the definition's model to model selection. `src/config/model-resolver.ts:1308-1335` gives explicit settings overrides precedence over agent defaults; `structured-subagent.ts:621` passes the agent's thinking level to the worker. `src/task/executor.ts:4381` uses the selected override or agent model; lines 4546-4552 warn on auth fallback to the parent.

The lane also validates all four files with omp's installed `parseAgent` and its real discovery loader against both project and user-home symlinks under `/tmp/agent-sync/`, without installing into the owner's profile or making model requests.
