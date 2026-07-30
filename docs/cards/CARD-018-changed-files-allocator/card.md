---
id: CARD-018
type: task
layer: core
reqs: [REQ-004, REQ-022]
title: The changed-files allocator against the port
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-017]
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
estimated_lines: 458
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The changed-files packer is the highest-risk module in the repository — five fix rounds of history — and it must never cause section-level truncation. Behaviour must not change here at all.

## Acceptance criteria
- [ ] `pack_changed_files` and `_stretch` take a `SourceTree` (REQ-004)
- [ ] Greedy admission, give-back and re-admission behaviour is unchanged (REQ-004)
- [ ] Goldens are byte-identical on the budget-filling and windowing fixtures (REQ-022)

## Notes
Assembled by greedy admission in hunk-count order: keep each file whose cheapest rendering still fits, name the rest. Whole file where it fits, hunk-centred windows where it does not, always line-numbered.

At 458 against a 500 ceiling this is one of the tightest cards on the board. The trailer is deliberately CARD-019's, not this card's.
