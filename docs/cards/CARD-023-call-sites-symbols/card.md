---
id: CARD-023
type: task
layer: core
reqs: [REQ-001, REQ-022, REQ-025]
title: pack/call_sites — symbol extraction (pure, no port)
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-016]
branch: ""
worktree: ""
design_pr_url: ""
pr_urls: []
split_slices: 0
adrs: []
reworks:
  slice: 0
  design: 0
  implement: 0
  split: 0
  deliver: 0
review_lenses_failed: []
estimated_lines: 370
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
Definition-shaped names are derived from the diff alone — no filesystem, no tree. Moving that half first gives `pack_call_sites` something to import, so the suite stays green before any port work begins.

## Acceptance criteria
- [ ] `changed_symbols`, `_module_stem`, `_suffix` and `CODE_SUFFIXES` live in `core/pack/call_sites.py` and take no `root` argument (REQ-001)
- [ ] The symbol hit ceiling is unchanged (REQ-001)
- [ ] `TestChangedSymbols` (`tests/test_context.py:1370-1435`) and `TestModuleStem` (`:1541-1560`) move with them (REQ-025)
- [ ] Goldens are byte-identical (REQ-022)

## Notes
**Nothing in this card touches a `SourceTree`.** `changed_symbols` takes a diff, `_suffix` and `_module_stem` take a path, and REQ-004 binds `pack_*` assemblers only — so the inherited criterion '`changed_symbols` takes a `SourceTree`' would be unsatisfiable here and belongs to CARD-024 (intake run 4, advisory A4).

The seam works because `pack_call_sites` needs these three names as *imports*, not as co-located code: after this card, `review.py`'s `pack_call_sites` imports them from the new module and behaviour is unchanged. Verified against `review.py:1488`, `:1503` and `:1425` by intake run 4.
