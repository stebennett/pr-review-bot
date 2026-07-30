---
id: CARD-017
type: task
layer: core
reqs: [REQ-004, REQ-022]
title: File reading and windowing against the port
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
estimated_lines: 304
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The first assemblers to lose their `root is None` branching. Reading a file and choosing a window are the operations every other pack part is built on.

## Acceptance criteria
- [ ] `read_source`, `_whole_file_body`, `_file_body` and `_file_tiers` take a `SourceTree` (REQ-004)
- [ ] No `root is None` branching remains in them, assertable by grep (REQ-004)
- [ ] Goldens are byte-identical (REQ-022)

## Notes
None yet.
