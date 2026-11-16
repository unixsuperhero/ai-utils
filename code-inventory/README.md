# code-inventory

Maps a Go module's unnamed data (largest structs and their field readers and
writers, field clusters, repeated field groups, hand-decoded maps, tuples, ids
built in strings), a responsibility-by-subject grid and size facts, and writes
`report.md` plus one TSV per table. Observations only. It reads the code; it
runs nothing.

```sh
~/hub/ai/utils/code-inventory/code-inventory ~/proj/some-module --out /tmp/inv
~/hub/ai/utils/code-inventory/code-inventory --help
```

The bash entry builds the Go program here into
`${XDG_CACHE_HOME:-~/.cache}/code-inventory/` when its sources change.
How to run and read it: [SKILL.md](SKILL.md). Rules for the o-family:
[rules/ofam.json](rules/ofam.json) (reproduces `~/hub/tools/data-inventory`'s
responsibility tags exactly).

Files: `rules.go` (rule table, rules-file merge, pure classifiers),
`load.go` (loading and the per-node walk), `analyze.go` (clusters, groups,
matches, grid), `tests.go` (tests reaching the largest struct's constructor),
`report.go` (report.md and the TSVs), `main.go` (flags). Tests:
`GOWORK=off go test .` (one test per rule kind, an end-to-end run over
`testdata/fixture`).
