---
id: CARD-050
type: task
layer: app
reqs: [REQ-001, REQ-012]
title: Extract app/review
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-044, CARD-045, CARD-049]
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
estimated_lines: 270
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
`review_pr` and `review_diff_file` are the two top-level flows. Once they are in `app/`, the only thing left in `review.py` is argument parsing and `main`.

## Acceptance criteria
- [ ] `review_pr` and `review_diff_file` live in `app/review.py` (REQ-001)
- [ ] Posting still requires explicit opt-in and `--dry-run` still wins (REQ-012)
- [ ] v1 remains review-only: nothing merges, pushes, labels or edits (REQ-012)

## Notes
**Posting requires explicit opt-in** (`--post`, or `DRY_RUN=0`). `resolve_post()` is the only place that decides, and `--dry-run` always wins.

**v1 is review-only.** An `approve` verdict posts an approving review and stops.
