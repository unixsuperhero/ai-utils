# AI utilities

## aiview moved

aiview now lives at `~/proj/o-ai` ([github.com/unixsuperhero/o-ai](https://github.com/unixsuperhero/o-ai)) as the family tool `o-ai`; its git history was merged there on 2026-10-24. Run it as `o ai …` or `mtm ai …`; its TUI is `o tui` after `o-nabe extension register o-ai`. The `aiview/` directory here is frozen and will be removed later. `aiwork.zsh` stays here.

## aiwork — named OMP workspaces

A zsh function for creating reusable workspace profiles and starting fresh [OMP](https://github.com/can1357/oh-my-pi) sessions. Profiles live centrally, not inside your projects. It supports one or multiple project directories and preserves your existing `omp` shell function and model/authentication defaults.

### Install

Requirements: zsh and `omp` on your PATH, already configured with your preferred model and authentication.

Clone this repository wherever you keep tools:

```zsh
git clone https://github.com/unixsuperhero/ai-utils.git ~/hub/ai/utils
```

Add this line to `~/.zshrc` (adjust the path if you cloned elsewhere):

```zsh
source "$HOME/hub/ai/utils/aiwork.zsh"
```

Run that same `source` command in your current terminal, or open a new terminal. No installation script or additional dependencies are needed.

OMP must allow standalone `AGENTS.md` discovery. Check:

```zsh
omp config get disabledProviders --json
```

If the list contains `agents-md`, remove that entry from your OMP configuration (normally `~/.omp/agent/config.yml`). Keep other exclusions intact. The tool does not change your global OMP configuration.

### Usage

```zsh
cd ~/projects/frontend
aiwork new frontend
aiwork new review "Focus on architecture and database boundaries."
aiwork new fullstack "Keep frontend and backend conventions separate." --add-dir ../backend

aiwork list
aiwork start fullstack
aiwork start fullstack "Where is authentication handled?"
aiwork help
```

- `new NAME ["INSTRUCTIONS"] [--add-dir DIR ...]` saves the current directory plus additional project roots. Quote instructions as one argument. Existing profiles are never overwritten.
- `start NAME [OMP_OPTIONS_OR_PROMPT ...]` opens OMP with the profile directory as its working directory and each saved project as an additional workspace root. Extra arguments pass through to OMP.
- `list` prints saved profile names.
- `help` prints command usage.

`new` creates a compact generic briefing with project paths, on-demand research guidance, and your instructions. It does not launch AI or automatically analyze the codebases. Maintain a concise architecture/source map in the profile's `AGENTS.md` when useful.

### Storage and fresh context

By default, each profile lives in `~/.config/omp-workspaces/NAME/`:

| File | Purpose |
| --- | --- |
| `AGENTS.md` | Reusable briefing and additional instructions |
| `roots.txt` | Absolute project directories, one per line |
| `fresh.yml` | Launch-only `autoResume: false` setting |

Edit these central files to update instructions, project roots, or launch settings. Set `AIWORK_HOME` to use another central storage directory. Profile names allow letters, digits, underscores, hyphens, and dots, but cannot start with a dot. Project paths may contain spaces, but not newlines. Missing project directories fail before OMP launches.

Normal launches start fresh conversations rather than replaying saved history. Explicit OMP resume options can still intentionally resume a session. Session saving remains enabled. Normal system/tool/repository instructions still consume context; a fresh session is not an empty system prompt.

These are workspace profiles, not separate OMP authentication/model profiles. Personal profiles, credentials, and machine-specific project paths are not included in this repository.

### Verification

The packaged script was smoke-tested with temporary central storage: creation, listing, duplicate/traversal rejection, paths containing spaces, and no writes into the project directory. Actual OMP RPC startup confirmed the generated briefing and project root were loaded with zero conversation messages. No model request was needed for the startup check.

## mgmt — itemize, review, apply

Reusable skill: [`mgmt/SKILL.md`](mgmt/SKILL.md). Terminal tool: [`mgmt/mgmt.py`](mgmt/mgmt.py). Requires Python 3 on macOS/Linux; no third-party dependencies.

Tell your assistant:

```text
Read ~/hub/ai/utils/mgmt/SKILL.md and use it to itemize [the material I specify].
Let me review the items before changing anything.
```

The assistant creates an inventory and persistent session, then gives you a command:

```sh
python3 ~/hub/ai/utils/mgmt/mgmt.py review /path/to/session.json
```

In the terminal checklist:

```text
show 3
check 3
action 4 rewrite more concisely
note 4 Preserve the examples
uncheck 3
done
```

Every decision saves immediately. Reopen the same session to continue. Unselected items remain untouched. Checking selects the action established for that session; custom actions are unrestricted text.

Then tell the assistant: **“Apply the mgmt session at /path/to/session.json.”** The skill's apply phase executes your selections and records verified results. The CLI's `apply` command produces a locked work queue for the assistant, **not standalone execution of arbitrary instructions**. Completed items are skipped on subsequent applies; interrupted operations require reconciliation before retrying.

Sessions default to `~/.local/state/mgmt/`, outside your project. They contain source excerpts and decisions; session files are owner-readable/writable only. Nothing is installed into global skill discovery automatically: load the skill by path as above, or register its directory through your assistant's existing skill mechanism.

Verified with a disposable source file: terminal review commands, reopening saved choices, selected-only removal by an executor, completion receipts, repeated-apply exclusion, interrupted-run protection, private session permissions, and overwrite rejection.
