---
id: CARD-043
type: task
layer: adapters
reqs: [REQ-013, REQ-015, REQ-028]
title: Swap the GitHub write path to githubkit
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-042]
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
Posting a review is the one write this program performs, and the 422 inline-comment fallback is the behaviour most easily lost in a client swap.

## Acceptance criteria
- [ ] Review posting goes through the client (REQ-013)
- [ ] The 422 inline-comment fallback still folds comments into the body, proved against the stub (REQ-028)

## Notes
This card carries **no** manual test plan: REQ-028 admits exactly two exemptions (CARD-041 and CARD-042), and the 422 fallback is stub-testable (intake run 4, advisory A7).
