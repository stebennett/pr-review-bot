---
id: CARD-009
type: task
layer: core
reqs: [REQ-001, REQ-012, REQ-022]
title: Extract core/marker; the marker owns round and SHA recovery
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-006]
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
estimated_lines: 169
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The marker is this program's only state. Round number and last-reviewed SHA are recovered from an HTML comment the adjudicator writes as the first line of its own review body — there is no database, no labels, no files. Parsing that body is pure domain logic and belongs in the core.

## Acceptance criteria
- [ ] `MARKER_RE` parse and compose live in `core/marker.py`; parsing is pure, takes a body string, and returns the `(round, sha)` pair or `None` (REQ-001)
- [ ] `prior_rounds` in `review.py` delegates to `core/marker`; no second `MARKER_RE` parse exists anywhere in the package (REQ-001)
- [ ] No module introduces persistence; round number and last-reviewed SHA come only from the marker (REQ-012)
- [ ] Goldens are byte-identical (REQ-022)

## Notes
`prior_rounds` splits three ways: this card owns the parse, CARD-035 owns fetching review bodies and parses nothing, CARD-044 orchestrates the two and applies `max_rounds`. The second acceptance criterion exists because that split spans three milestones — without it, the old inline parser at `review.py:672-686` could coexist with `core/marker.py` for the whole window (intake run 4, advisory A1).

The marker format spec lives in `doctrine/verdict.md`. If a new piece of state is ever needed, it belongs in the marker.
