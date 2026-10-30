# Sol prompts for o-family work

Prompts for running o-family ("ofam") work with **Sol**: OpenAI Codex CLI, model `gpt-6-sol` (`~/.codex/config.toml`). They are the Codex counterparts of the Claude agents `ofam-lane`, `ofam-planner` (`../../agents/`), `ux-reviewer` and `ux-applier` (`~/hub/ai/agents/`). Codex does not load those agent definitions, so each prompt carries its own rules.

## What Codex already loads (not repeated here)

- `~/.codex/AGENTS.md` links to `~/hub/ai/instructions/AGENTS.md`, the global rules: deterministic work, "the main agent orchestrates; subagents do the work", TUIOS startup and mail. Every run gets them.
- The `AGENTS.md` files from the git root of `-C <dir>` down to it: a run in `~/proj/ochazuke/.worktrees/x` gets the worktree's ochazuke guide (`project_doc_max_bytes = 65536` keeps it whole).
- `~/hub/AGENTS.md` (the family rules) loads only for runs under the hub repo. The prompts therefore carry the family rules, the ochazuke invariants and the coordinator's standing rules (the Claude memory notes) themselves.

Check what a run will see with `(cd <dir> && codex debug prompt-input)`.

## The prompts

| File | Role | Run it in | Sandbox |
|---|---|---|---|
| [`coordinator.md`](coordinator.md) | Plans, briefs lanes, launches them as background `codex exec` runs, reviews diffs, gates, merges, pushes, tags, reinstalls `~/bin`, keeps `o-plans` and the answers page | `~/hub` (interactive) | the config default (`danger-full-access`): it merges, pushes and installs |
| [`lane.md`](lane.md) | One implementation lane in its own worktree; commits on the lane branch, never ships. Also applies a UX punch list | the lane worktree | `workspace-write` plus `--add-dir`s (below) |
| [`planner.md`](planner.md) | Designs and plans, file:line evidence, writes only `~/hub/o-plans/`, owner questions in the scanned format | `~/hub/o-plans` | `workspace-write` |
| [`research.md`](research.md) | Read-only investigation, every claim with `path:LINE` | the repo | `read-only` |
| [`ux-review.md`](ux-review.md) | Read-only interaction review against ochazuke `docs/UX-RULES.md`, stories and live `tui-drive` walks; punch list | a scratch dir `/tmp/ux-<name>` (`--skip-git-repo-check`, plus the Go cache `--add-dir`s) | `workspace-write` (writes only the scratch dir) |
| [`vhs.md`](vhs.md) | VHS tapes in the house style, gallery pages, `vhs-tutorial` pages | the repo's worktree or `~/hub/test-archive/<date>/vhs` | `workspace-write` |
| [`brief-template.md`](brief-template.md) | The fill-in brief for one lane; each `## KEY` section fills a `{{KEY}}` in `lane.md` | | |
| [`render.py`](render.py) | Fills `{{KEY}}` from a brief or `KEY=VALUE` / `KEY=@file`; refuses while a key is empty | | |

## Division of labour

The **coordinator** thinks, plans, briefs and verifies; it changes no code itself. **Lanes** implement, one per worktree and branch (`<repo>/.worktrees/<lane>`, scratch in `/tmp/<lane>/`), commit, and report in a fixed shape; they never merge, push, tag or install. The **planner** writes plans before lanes are briefed; **research** answers questions without changing anything; **ux-review** returns a punch list that goes back to a lane as its task. The coordinator reviews every diff, re-runs the repo's gate ("Full gate per repo" in `lane.md`; matomeru's `cmd/mtm` race suite runs in four test-name chunks), merges, pushes once green, reinstalls binaries, trims the Go build cache past ~25 GB (entries untouched 2+ hours, never mid-build, never `go clean -cache` during lanes) and updates `~/hub/o-plans`. Lanes stop and report under 4 GiB free disk.

Codex runs one agent per process, so the coordinator launches each lane as a background `codex exec` in that lane's worktree, records its PID and waits on the PID (never `pgrep -f`). Some Codex builds also offer `spawn_agent`; those agents share the parent's working directory, so use it only for read-only research or review.

## Running them

### Non-interactive (`codex exec`)

Prompts without placeholders take the task appended after the prompt:

```sh
P=~/hub/ai/utils/prompts/sol
codex exec -m gpt-6-sol -C ~/proj/o-json --sandbox read-only \
  "$(cat $P/research.md) Task: where does o-json read its settings file?"

codex exec -m gpt-6-sol -C ~/hub/o-plans --sandbox workspace-write \
  "$(cat $P/planner.md) Task: plan o-json nested tables from plans/o-json.md and the hover prototype."
```

`lane.md` has placeholders (`{{REPO}} {{BASE}} {{LANE}} {{TASK}} {{DONE_WHEN}} {{TRAILER}}`). Fill a brief, render it, and launch it in the worktree:

```sh
REPO=~/proj/ochazuke LANE=std-verbs-s1 L=/tmp/std-verbs-s1
mkdir -p $L && git -C $REPO worktree add .worktrees/$LANE -b $LANE main
cp $P/brief-template.md $L/brief.md && $EDITOR $L/brief.md
python3 -I $P/render.py $P/lane.md $L/brief.md > $L/prompt.md
env -u TUIOS_ENV -u TUIOS_SESSION -u TUIOS_PANE_ID \
  nohup nice codex exec -m gpt-6-sol -C $REPO/.worktrees/$LANE --sandbox workspace-write \
    --add-dir $REPO/.git --add-dir ~/.cache/go-build --add-dir ~/.cache/go-tmp --add-dir ~/go/pkg/mod \
    -o $L/report.md - < $L/prompt.md > $L/log.txt 2>&1 &
echo $! > $L/pid
while kill -0 "$(cat $L/pid)" 2>/dev/null; do sleep 60; done; cat $L/report.md
```

- `workspace-write` keeps `.git` read-only, so a lane cannot commit without `--add-dir $REPO/.git`; Go's build and module caches need `--add-dir` too. `/tmp` is writable.
- Unsetting `TUIOS_*` stops a lane from reading (and marking read) the launching pane's mail.
- Single values can be given on the command line instead: `render.py lane.md brief.md BASE=v0.54.0 TRAILER=@trailer.txt`.

### Interactive (`codex`)

- Start in the right directory with the right sandbox: `codex -m gpt-6-sol -C ~/hub` for the coordinator.
- Paste the prompt as the first message: `pbcopy < $P/coordinator.md`, paste, then add the task. For a lane, paste the rendered `$L/prompt.md`.
- Or install them as Codex custom prompts and pick them with `/prompts`: `mkdir -p ~/.codex/prompts && for f in coordinator lane planner research ux-review vhs; do ln -sfn $P/$f.md ~/.codex/prompts/ofam-$f.md; done`, then type `/prompts:ofam-research` and the task. Codex custom prompts fill `$ARGUMENTS`/`$1`-style arguments, not `{{KEY}}`; for `lane.md` use the rendered file.

## Keeping them current

The rules come from `~/hub/AGENTS.md` (family rules), `~/hub/ai/instructions/AGENTS.md` (global), ochazuke's `AGENTS.md` and `docs/UX-RULES.md`, `~/hub/o-plans/README.md`, the Claude agents above, the VHS house style (`~/hub/test-archive/2026-10-29/vhs/HOUSE-STYLE.md`) and the coordinator's memory notes. When one changes, update the prompt that carries it, and the gate commands in `lane.md` when a repo's gate changes.
