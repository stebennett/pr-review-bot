---
id: CARD-019
type: task
layer: core
reqs: [REQ-004, REQ-022]
title: The dropped-file trailer against the port
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-018]
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
estimated_lines: 108
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
Naming the files that did not fit is what stops a lens reading absence as evidence. It is small, separable, and easier to reason about away from the allocator.

## Acceptance criteria
- [ ] `_trailer_groups` and trailer rendering take a `SourceTree` (REQ-004)
- [ ] The dropped-file trailer still names every admitted-but-unrendered file (REQ-004)
- [ ] Goldens are byte-identical (REQ-022)

## Notes
Split out of the allocator card because the two together are ~513 changed lines (intake run 2, finding B8).
