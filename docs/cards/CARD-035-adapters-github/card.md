---
id: CARD-035
type: task
layer: adapters
reqs: [REQ-001, REQ-028]
title: Extract adapters/github and the HTTP helper
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-034]
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
estimated_lines: 472
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
Every GitHub call in the program lives in one place after this, which is what lets CARD-040 swap its transport and CARD-042 swap its client without touching anything else.

## Acceptance criteria
- [ ] `GitHub`, `whoami`, `post_review`, `repo_config` and `describe_key` live in `adapters/github.py` (REQ-001)
- [ ] Fetching prior review bodies returns bodies only and performs no parsing (REQ-001)
- [ ] The 422 inline-comment fallback is exercised against the stub server (REQ-028)

## Notes
Inline comments that anchor to an untouched line make GitHub reject the **entire** review, so `post_review()` folds them into the body on a 422. `anchor_violations` logs findings anchored outside the diff and never drops them — a real bug at a slightly wrong line is worth more than a clean log.

This card owns the fetch half of `prior_rounds`: CARD-009 owns the parse, CARD-044 the orchestration. It must parse nothing.

At 472 this card is near the ceiling and should not absorb further scope.
