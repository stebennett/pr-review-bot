---
id: CARD-020
type: task
layer: core
reqs: [REQ-004, REQ-025]
title: Convert the changed-files inclusion and skipping tests
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-019]
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
estimated_lines: 400
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
`TestPackChangedFiles` is the largest test class in the repository and drives the riskiest module. Converting it to `InMemoryTree` in three themed changes keeps each reviewable.

## Acceptance criteria
- [ ] The inclusion and skipping tests from `TestPackChangedFiles` use `InMemoryTree`, not a temp directory (REQ-025)
- [ ] They live under `tests/core/pack/` (REQ-025)
- [ ] Test-count parity with the block being replaced (REQ-004)

## Notes
One of three siblings — CARD-020, CARD-021, CARD-022 — carving `tests/test_context.py:770-1369` (~600 source lines, ~1,200 changed). The cut points are chosen so each child lands near 400, **not** at the 150/280/170 division an earlier proposal named, which would put the middle child at ~560 (intake run 3, advisory A6).

'Coverage no lower than before' is stated as test-count parity plus the named utilisation tests still being present, because no coverage tool is in the dev dependencies (intake run 2, finding A5).
