---
id: CARD-047
type: task
layer: app
reqs: [REQ-001, REQ-025]
title: Convert the build_context tests — assembly and notes
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-045]
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
estimated_lines: 352
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The worktree-acceptance and degradation-note tests are what pin the labelling behaviour CARD-053 later changes deliberately. They need to be correct and readable before that card touches them.

## Acceptance criteria
- [ ] The pack-assembly and worktree-note tests from `TestBuildContext` (`tests/test_context.py:381-556`) live under `tests/app/` (REQ-025)
- [ ] The truncated-conventions-fence case still asserts a balanced fence (REQ-001)

## Notes
Sibling of CARD-046. See that card's notes on the cut point.
