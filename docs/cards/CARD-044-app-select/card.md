---
id: CARD-044
type: task
layer: app
reqs: [REQ-001, REQ-012]
title: Extract app/select
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-035]
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
estimated_lines: 282
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
Selection, triage and round counting are ordinary deterministic code, and keeping them that way is the point of this repository. They belong in `app/`, orchestrating the adapter and the core rather than containing either.

## Acceptance criteria
- [ ] Candidate selection, triage and round counting live in `app/select.py` (REQ-001)
- [ ] Round counting calls the adapter for review bodies, folds them through `core/marker`, and applies `max_rounds` (REQ-001)
- [ ] Drafts and Renovate-authored PRs are still never selected (REQ-012)

## Notes
**Drafts and Renovate-authored PRs are never reviewed** — in any mode, not even with an explicitly named PR or `--force`. A draft has not been offered for review; Renovate PRs belong to the separate `renovator` skill and the two must never contend over a PR.

This is the third of `prior_rounds`' three homes: CARD-009 parses, CARD-035 fetches, this card orchestrates.
