---
id: CARD-026
type: task
layer: core
reqs: [REQ-004, REQ-025]
title: Convert the call-sites and determinism tests to InMemoryTree
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-024]
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
estimated_lines: 334
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The determinism assertions are the ones that matter most here: the pack must be deterministic for a before/after golden comparison to mean anything.

## Acceptance criteria
- [ ] `TestPackCallSites` and `TestPackCallSitesDeterminism` (`tests/test_context.py:1561-1727`) use `InMemoryTree` (REQ-025)
- [ ] Determinism assertions still hold — needles are built from ordered structures, never by iterating a `set` (REQ-004)

## Notes
If you add a pack part, build its needles from an ordered structure. Iterating a `set` makes the pack non-deterministic and silently destroys the golden net's value.
