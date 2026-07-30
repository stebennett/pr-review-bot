---
id: CARD-038
type: task
layer: adapters
reqs: [REQ-005, REQ-028]
title: RecordingModelClient and panel dispatch tests
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-036]
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
estimated_lines: 230
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The staggered dispatch, the retry ladder and per-lens failure handling are the logic most likely to break in a refactor and the only logic that currently costs money to test. A recording fake makes all of it free.

## Acceptance criteria
- [ ] A `RecordingModelClient` fake implements `ModelClient` (REQ-005, REQ-025)
- [ ] Staggered dispatch, the retry ladder and per-lens failure handling are tested with no network call (REQ-005, REQ-028)

## Notes
`run_panel` dispatches the first lens alone to write the cache prefix, then the rest in parallel to read it. Three cold parallel calls would each pay the write premium and none would read, which is worse than not caching. Staggering is gated on `CACHE_ENABLED`.
