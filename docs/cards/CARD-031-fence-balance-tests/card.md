---
id: CARD-031
type: task
layer: core
reqs: [REQ-004, REQ-025]
title: Convert the fence-balance tests and their fixtures
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-027]
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
estimated_lines: 290
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
Fence balance under truncation is a swept property over every pack section and the assembled prompt — the one test that would catch a truncation cutting a fence in half.

## Acceptance criteria
- [ ] `TestFenceBalanceUnderTruncation` (`tests/test_context.py:2173-2272`) and the four fence fixtures (`:2128-2172`) live under `tests/core/pack/` (REQ-025)
- [ ] The sweep still asserts a balanced prompt at every budget (REQ-004)

## Notes
`unclosed_fence` is a **deliberate independent reimplementation** of `_open_fence` — its docstring says so — and must not be deduplicated against the core module, because an independent checker is the whole point. This card owns that rationale; the helper itself moves to `tests/helpers.py` in CARD-014, which is the first card that needs it there (intake run 4, advisory A6).
