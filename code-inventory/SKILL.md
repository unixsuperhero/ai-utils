---
name: code-inventory
description: Map a Go codebase's unnamed data, god structs and duplicated responsibilities before a refactor. Runs a static scanner over a module and writes report.md plus one TSV per table (largest structs and which functions read and write each field, field clusters, repeated field groups, hand-decoded maps, tuples, ids built in strings, a responsibility-by-subject grid, long functions, package and file sizes, tests that construct the largest struct). Use when the user wants an inventory, audit or map of a Go codebase's structure, or asks "where is the same job done twice", "what is in this god struct", "how big is this code" before refactoring.
---

# Inventory a Go codebase

Tool: `~/hub/ai/utils/code-inventory/code-inventory` (bash). Resolve the path from this skill's directory if installed elsewhere. It builds the Go program in this folder into `${XDG_CACHE_HOME:-~/.cache}/code-inventory/` on first run and again whenever its sources change (`CODE_INVENTORY_CACHE` overrides the folder), then runs it. Needs Go 1.26+ and the scanned module's dependencies in the module cache (or the network).

It only reads the code it scans. Point it at a clean checkout, or a detached worktree of a commit, so the report names a commit.

## Run

```sh
code-inventory PATH [--packages './...'] [--out DIR] [--structs 5] [--struct NAME]... [--rules FILE]...
```

- `PATH`: the module root (the folder with `go.mod`). Nested modules are not included by `./...`; run once per module.
- `--packages`: patterns relative to PATH, space or comma separated (`'./cmd/app ./internal/...'`).
- `--out`: output folder (default `$TMPDIR/code-inventory/<base of PATH>`). It prints the report path.
- `--structs N`: how many of the largest structs (by field count) to map field by field; `--struct NAME` (`Name`, `pkg.Name` or `import/path.Name`) adds one.
- `--rules FILE`: JSON that adds, overrides or replaces responsibility rules (format below). `rules/ofam.json` holds the o-family rules (daemon, keys, extract-context and the family packages).
- Thresholds: `--cluster 0.5 --cluster-low 0.3 --pair 0.5` (Jaccard), `--long 100` (lines), `--results 3 --params 4` (tuples), `--seps '/,:'` (id separators), `--top 20` (rows per table in the report), `--tests=false` (skip the test graph), `--link PREFIX` (file links).
- The scanned module is loaded with the environment you run it in. In a git worktree under a checkout that has a `go.work`, set `GOWORK=off` (or point it at the right file).

Run time (M-series Mac): about 6 k functions took 18 s with a cold build cache and 3 s warm; 300 functions took 8 s cold and 2 s warm. On a shared machine, queue it (`heavy nice -n 10 code-inventory ...`).

## Then

1. Run it and say where the report is.
2. If `mdoc` exists (`command -v mdoc`), open the report with `mdoc report.md` from the output folder.
3. Give a short summary: the Summary table's notable numbers and what the tool cannot see.
4. **Do not act on the results unasked.** The report is observations only; no refactor, no new plan, no edits, until the user asks for one.

## Reading the report

The header names the path, commit, packages, rule sources, thresholds and method; then the Summary; then "What the tool cannot see". Every table is complete in its TSV next to `report.md`; the report shows the top rows. Rerun and diff the TSVs to see change over time.

- **1a Largest structs**: every struct by field count, and for the mapped ones each field's reader and writer functions (from `go/types` selections; a write is an assignment, increment, address taken, element assigned or composite-literal key). Fields never read, read by one function, or written by 10+ are listed.
- **1b Clusters**: fields whose reader sets overlap (Jaccard, complete linkage). A cluster with many shared readers is data that travels together without a name.
- **1c Field groups**: the same `name type` fields repeated across struct types.
- **1d Hand-decoded maps**: constant-key indexes into string-keyed maps, interface-valued ones counted apart, and key sets decoded by more than one function.
- **1e Tuples**: functions returning 3+ values and parameter lists of 4+ that recur.
- **1f Ids built in strings**: joins and splits on the separators, and literal prefixes (`"task:"`) both built and taken apart.
- **2 Responsibilities**: each function tagged from what it calls, the types it names, the constructs it uses and its own name, by the printed rule table. Subjects come from the codebase's own exported type names and receiver types: the first found in the function name, then receiver, file, package. The grid is subject by responsibility; "done directly in several subjects" lists functions that call the library themselves (base) or a same-package mechanism (local).
- **3 Size**: packages, files, functions of `--long` lines or more, and how many `Test*` functions reach a `New*` constructor of the largest mapped struct that has one (a lower bound: interfaces and other packages' tests are not followed).

## Rules file

```json
{
  "replace": false,
  "responsibilities": ["persist", "daemon"],
  "rules": [
    {"tag": "daemon", "level": "named", "kind": "pkg", "pattern": "^example\\.com/app/internal/daemon(/|$)"},
    {"tag": "render", "level": "base", "kind": "own", "pattern": "^View", "with": "^strings\\.Builder$"},
    {"tag": "network", "kind": "pkg", "pattern": "^(net|net/http|net/rpc|net/smtp|crypto/tls)(/|$)", "drop": true},
    {"tag": "notify", "drop": true}
  ]
}
```

- `kind`: `pkg` (callee package path), `func` (`pkgpath.Name` of a package function), `callee` (callee name), `recv` (callee receiver type), `type` (`pkgpath.Name` of a named type used), `syntax` (`go`, `select`, `send`, `recv`, `make-chan`), `own` (the function's own name; with `with`, only when it also names a type or calls a package function matching `with`).
- `level`: `base` (a library or construct: the function does the job itself) or `named` (a convention or the codebase's own package: reported `local` in the same package, `uses` elsewhere).
- A rule with the same tag, kind and pattern as an existing one replaces it; `drop` removes it; a drop with only a tag removes the whole responsibility. `replace: true` starts from an empty table. `responsibilities` sets the column order.
