---
id: CARD-053
type: task
layer: app
reqs: [REQ-022, REQ-027]
title: `--worktree` verifies the checkout is at the PR head
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
estimated_lines: 210
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The one intended behaviour change in this whole refactor, landed last and alone so that the only stage where goldens are expected to move is the one where a change was actually requested — and the diff should be exactly one label.

## Acceptance criteria
- [ ] A worktree not at the PR head records a note, keeps the conservative label, and still produces a pack (REQ-027)
- [ ] A worktree at the PR head is labelled as such (REQ-027)
- [ ] The label predicate is correct for a rejected worktree that fell back to per-file API fetches (REQ-027)
- [ ] Goldens change in exactly the labelling and nowhere else (REQ-022)

## Notes
It **warns and degrades**; it does not reject. Rejecting a stale checkout would violate the standing rule that the pack must never fail a review, and would break the offline tuning loop `CLAUDE.md` prescribes.

This subsumes the parked minor at `review.py:2128`, where `local_checkout=bool(worktree)` labels a rejected worktree that fell back to per-file API fetches as 'not known to be at the PR head'. Computing the label correctly requires the correct predicate, so the fix arrives here rather than as separately reopened scope.
