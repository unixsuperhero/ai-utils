# Lane brief

<!-- Copy to /tmp/<lane>/brief.md and fill every section. Each `## KEY` section
fills the {{KEY}} placeholder in lane.md:
  python3 -I ~/hub/ai/utils/prompts/sol/render.py ~/hub/ai/utils/prompts/sol/lane.md /tmp/<lane>/brief.md > /tmp/<lane>/prompt.md
render.py refuses to print while a section is empty. Comments like this one are dropped. -->

## REPO

<!-- Absolute path of the main checkout, e.g. /Users/unixsuperhero/proj/ochazuke -->

## BASE

<!-- Branch or commit the lane starts from, usually main -->

## LANE

<!-- Short kebab-case name; it is the branch, the worktree (.worktrees/<lane>) and /tmp/<lane>/ -->

## TASK

**Goal.** <!-- One or two sentences: what the user can do afterwards. -->

**Plan.** <!-- ~/hub/o-plans/plans/<topic>.md and the lane row it implements, or "none". -->

**Which repo and why.** <!-- App, library or both; for a library change, the consumers and how they pick it up. -->

**Config checked.** <!-- The verbs/settings you listed and why configuration is not enough. -->

**Reuse.** <!-- reuse-scan <terms> hits: files to copy and adapt, what to keep and drop. Or "reuse-scan <terms> found nothing that fits". -->

**Scope.**
- <!-- what to build, file by file where known -->

**Out of scope.**
- <!-- what not to touch -->

**Settings and defaults.** <!-- The opt-out setting for any UI change, and its default; or "no UI change". -->

**Vim comparison.** <!-- For a Vim-like feature: the :help tags to start from; otherwise "n/a". -->

**Owner decisions that apply.** <!-- Quote them; they are final. -->

## DONE_WHEN

- Targeted tests and stories for the change pass; the coordinator owns the full gate unless this brief explicitly asks for it.
- <!-- the behaviour, the story names, the catalog/reference output, CHANGELOG Unreleased, codemap -->

## TRAILER

<!-- The exact trailer lines, copied verbatim, e.g. Co-Authored-By: … and Claude-Session: … -->
