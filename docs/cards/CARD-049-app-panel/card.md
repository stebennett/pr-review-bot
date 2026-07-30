---
id: CARD-049
type: task
layer: app
reqs: [REQ-001, REQ-012, REQ-025]
title: Extract app/panel
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-015, CARD-038]
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
The panel is where the four model calls happen and where an unsound verdict must be refused rather than posted. It is the last piece of orchestration to leave the monolith.

## Acceptance criteria
- [ ] Staggered dispatch, per-lens failure handling and consistency enforcement live in `app/panel.py` (REQ-001)
- [ ] An unsound verdict still raises rather than posting (REQ-001)
- [ ] One failing PR does not abort a pass (REQ-012)
- [ ] `TestDispatchLenses` (`tests/test_prompting.py:483-573`) moves under `tests/app/` (REQ-025)

## Notes
The consistency rules enforced after adjudication: approve implies `blocker_count == 0`, request-changes implies `>= 1`, and the body starts with the marker. Raise rather than post an unsound review.

**Only four steps call a model** — the three lenses and the adjudication. Each names its own model (`--model-lens`, `--model-verdict`) so a cheap model does the mechanical reviewing and a stronger one adjudicates. Don't collapse this.

At 472 this card is near the ceiling.
