---
id: CARD-007
type: task
layer: core
reqs: [REQ-001, REQ-010, REQ-022, REQ-025]
title: Extract core/target and core/schemas; parse_target raises
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-006]
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
estimated_lines: 242
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
`parse_target` calls `die()`, which lives in `reviewer/log.py` — a module the import boundary forbids to `core/`. Writing to stderr is a side effect and `die` counts as one, so the de-logging has to happen in the same change that moves the function, not afterwards.

## Acceptance criteria
- [ ] `parse_target` and the three schemas live in `reviewer/core/` (REQ-001)
- [ ] `parse_target` raises rather than calling `die`; `core/target.py` does not import `reviewer.log`; the entry point in `review.py` converts the exception to the same message and exit code, pinned by a test (REQ-010)
- [ ] Their tests move with them (REQ-025)
- [ ] Goldens are byte-identical (REQ-022)

## Notes
`die` is the easy one of the three log functions to miss, because it reads as an error path rather than as logging. Before extracting any function into `core/`, grep it for `log()`, `vlog()` **and `die()`**.

The exception conversion lands in `review.py`'s entry point for now; CARD-051 carries it into `app/cli.py` when that module exists.
