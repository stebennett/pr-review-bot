---
id: CARD-051
type: task
layer: app
reqs: [REQ-001, REQ-002, REQ-012, REQ-025]
title: Extract app/cli and reduce review.py to a shim
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-050, CARD-046, CARD-047, CARD-048]
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
estimated_lines: 430
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The end of the monolith. `review.py` becomes a three-line shim, the container entrypoint stays `/app/review.py`, and every documented command keeps working verbatim.

## Acceptance criteria
- [ ] `build_parser`, `resolve_post`, `resolve_cache` and `main` live in `app/cli.py` (REQ-001)
- [ ] `review.py` is three lines (REQ-002)
- [ ] Every command in `CLAUDE.md` and `README.md` runs unchanged (REQ-002)
- [ ] No module introduces persistence; round number and last-reviewed SHA come only from `MARKER_RE` (REQ-012)
- [ ] One failing PR must not abort a pass — `main` still catches per-PR and per-repo and counts failures into the exit code (REQ-012)
- [ ] `TestResolvePost` and `TestResolveCache` (`tests/test_prompting.py:416-482`) move under `tests/app/` (REQ-025)

## Notes
`review.py` resolves `doctrine/` and `.env` relative to its own file, so it runs from any cwd. That must survive the shim.

This card `depends_on` CARD-046, CARD-047 and CARD-048 as well as CARD-050: reducing `review.py` to three lines breaks every test still addressing `review.*`, and nothing else within M6 orders this card after the `build_context` test conversions (intake run 4, advisory A5).

The `parse_target` exception conversion, parked in `review.py`'s entry point by CARD-007, lands in `app/cli.py` here.
