# Run plan

| Step | What | Depends on | Measured by (inventory table, metric, target) | Result (measured) | Status |
|---|---|---|---|---|---|
| 1 | Inventory | | report.md written | | |
| 5 | Vertical slice: <group> | spine accepted | lines, repeated groups, hand-decoded keys before/after | | |
| 6a | Batch: <group> (codemod) | 5 | same metrics | | |
| 7 | Rule checks and shrink-only baselines | 6a | check runs in seconds; baseline rows only shrink | | |
| 7b | Remove old mechanism | last batch | old mechanism callers = 0 | | |
