---
name: systematic-restructure
description: Plan and run a fundamental, systematic restructuring of a whole codebase (shrink size, remove duplication, make behaviour data-driven, no special cases) so small unplanned increments do not introduce inconsistencies. Steps - measure with a deterministic inventory, design one small spine of shared contracts for all parts, map every concept onto it, settle open questions with the owner in a discussion document, prove the spine on one vertical slice, migrate the rest in measured mechanical batches, then lock it with shrink-only rule checks. Use when asked to restructure, consolidate, de-duplicate or "make everything consistent" across a codebase, or before any refactor touching most packages.
---

# Systematic restructure

Language-agnostic method. Templates are in `templates/` next to this file (resolve from this skill's directory). Keep all working files in one folder outside the code (a plans folder), not in the target repo, until the owner asks otherwise.

## 0. When to use

Use for a change that touches every part of a codebase and must end consistent: smaller size, one implementation per job, behaviour declared as data, no special cases. Do not use for a local fix or one feature. If small increments would each look fine yet leave the parts different from each other, use this.

Rules for the whole method:
- Label every statement **fact** (measured or read, with a file or number) or **proposal**.
- Numbers come from programs. Re-measure after every step; never carry an old number forward.
- Do not act on a step's output until the next step says to. Inventory reports observe only.

## 1. Inventory, deterministically

Run a program, do not read the code and guess. Go: `~/hub/ai/utils/code-inventory/code-inventory PATH --out DIR` (see `code-inventory/SKILL.md`; `GOWORK=off` in a worktree). Other languages: build or find an equivalent scanner (an AST or compiler-API walk, not grep alone) and keep its output as TSV so it can be diffed. It must measure:

- god structs/classes: field count and which functions read and write each field;
- field clusters that travel together, and the same field group repeated across types;
- hand-decoded maps (constant keys read from string-keyed or untyped maps);
- tuples: functions returning 3+ values or taking long repeated parameter lists;
- ids glued from strings (joins/splits on separators, literal prefixes built and parsed);
- a responsibility by subject grid: the same job (persist, render, validate, send...) written separately for several subjects (nouns);
- a per-concept table of what is data and what is code (declared vs hand-written per concept);
- size facts: lines per package, file and function; and tests that boot the whole app to test one thing.

Save the TSVs and a `report.md`. Open the report for the owner (`mdoc report.md` if available). Stop: report only, no actions.

## 2. Design the spine for all parts

Before building anything, design the few shared contracts everything will be built from, for the whole codebase at once. Typical contracts (pick what the inventory justifies):
- the concept (noun) declaration schema: what a concept declares as data;
- the context value every operation receives (one value, not many parameters);
- reference values for things that point at other things. Respect parent/child shape: a child ref may carry its parent; a parent stands alone with 0..n children. Do not force independent pairs into one value;
- the storage contract;
- generic views/pages driven by declarations;
- one implementation per responsibility.

Write each as a section of `spine.md` (`templates/spine.md`): shape, rules, what it replaces (with inventory numbers), and what is explicitly out of scope. Stay at contract level. Do not plan each feature's code.

## 3. Map every concept and feature onto the spine

One table (`templates/mapping.tsv`), one row per concept and per feature: what it declares as data, which shared parts it uses, what stays custom code and why. Fill it from the inventory, mechanically where possible. A row that does not fit is a spine question: raise it now, as an open question, not later as a special case.

## 4. Discuss with the owner before building

Write one discussion document (`templates/discussion.md`): the owner's prompt word for word, facts measured, the spine, the mapping, then numbered open questions. Each question has a recommended answer with a reason, and options as concrete choices (name what each does, never bare yes/no). Open it for the owner (`mdoc`, or the team's question tool). Record answers word for word. Log each outcome in `decisions.md` (`templates/decisions.md`) with whose decision it is (owner, or delegated). Keep facts and proposals labelled. Update the spine and mapping with the answers. Build nothing until the owner has answered, or has said to proceed on the recommendations.

## 5. Prove the spine on one vertical slice

Pick the most typical group of concepts and carry it end to end through the new contracts: declaration, operations, storage, views, tests. Measure before and after with the inventory (lines, duplicated groups, hand-decoded keys, tests per concept). Then revise the spine with what the slice showed, and re-state the changed contracts and any mapping rows in the discussion document. Do not start step 6 until the revised spine is accepted.

## 6. Migrate the rest in mechanical batches

Order the groups in `run-plan.md` (`templates/run-plan.md`: step, depends on, measured by). For each group: write a codemod (AST rewrite or script) and apply it; hand-edit only the remainder; run the group's targeted tests; re-run the inventory and record the delta. One group per commit or batch, so a regression is easy to bisect. Rewrite old callers in the same batch that adds the new mechanism, and delete the old one when its last caller moves.

## 7. Make drift impossible

For each spine rule, add one automated check that fails when it is broken (for example: no hand-decoded map outside the decoder; no id built from strings; one implementation per responsibility; no branch on a concept name). Existing violations go in a baseline file per check. Baselines are shrink-only: the update flag may only remove rows, never add them. Checks run in seconds and run first in every gate, before the slow suite. Old and new mechanisms must not coexist long: set a removal step in the run plan. When a shared library changes, ship it in the same change set as the app build that uses it, so no consumer runs the old contract.

## 8. Anti-patterns

- Planning every feature's code-level detail before any code meets the design (step 5 exists to correct the design).
- Increments with no target: each change must move a measured number in the run plan.
- A second mechanism added beside an old one and left there.
- Special cases that branch on a name (concept, mode, tool). If one seems needed, the spine is missing a field: stop and raise it.
- Numbers quoted from earlier runs instead of re-measured.
- Acting on the inventory report before the spine is discussed.

## Outputs

- Inventory folder: `report.md` and TSVs (re-run after each step).
- `spine.md`: contracts, one section each.
- `mapping.tsv`: every concept and feature mapped.
- `discussion.md`: prompt, facts, spine, mapping, numbered questions, owner answers.
- `decisions.md`: decisions table with owner.
- `run-plan.md`: steps with dependencies and the measure for each.
- The slice's before/after numbers, per-batch deltas, and the rule checks with shrink-only baselines.
