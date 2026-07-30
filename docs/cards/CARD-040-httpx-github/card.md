---
id: CARD-040
type: task
layer: adapters
reqs: [REQ-013, REQ-028]
title: Adopt httpx for the GitHub transport
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-035, CARD-039]
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
estimated_lines: 300
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
`_http` has no real timeouts. Every GitHub call in a CronJob that fires unattended is one hung socket away from a review that never completes.

## Acceptance criteria
- [ ] GitHub calls go through httpx with an explicit timeout on every request (REQ-013)
- [ ] Tests drive them against the stub server (REQ-028)

## Notes
None yet.
