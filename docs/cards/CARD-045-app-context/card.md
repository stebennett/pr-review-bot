---
id: CARD-045
type: task
layer: app
reqs: [REQ-001, REQ-010, REQ-022]
title: Extract app/context
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-032, CARD-033]
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
estimated_lines: 364
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
`build_context` is where the degradation ladder is actually chosen. Once every rung is a `SourceTree` implementation, this becomes a small function that picks one and records why — which is all it should ever have been.

## Acceptance criteria
- [ ] `build_context` selects a `SourceTree` implementation and records a note per degradation (REQ-001)
- [ ] It emits the diagnostics `core/` returned as data (REQ-010)
- [ ] Goldens are byte-identical including `ctx.notes` (REQ-022)

## Notes
**The pack must never fail a review.** Every acquisition and assembly path degrades — to a per-file API fetch, then to a smaller pack, then to no pack — recording a note in `ctx.notes`. A thin review beats no review, so `build_context` catches broadly and still yields.

The corollary matters when working here: a bug in a pack part degrades silently instead of raising, so pack parts earn their correctness from tests, not from runtime noise.
