---
id: CARD-032
type: task
layer: core
reqs: [REQ-004, REQ-006, REQ-010, REQ-022, REQ-025]
title: pack/requirements, the IssueSource port, and fetch failures as notes
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-016]
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
estimated_lines: 297
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
Requirements resolution reads the PR body, up to five linked issues and human PR comments. Nothing on that path should be able to post, so it gets a narrow read-only port rather than the whole GitHub client. Its `vlog()` calls also have to become data, because the boundary forbids logging from `core/`.

## Acceptance criteria
- [ ] `ports.py` defines `IssueSource` with `issue` and `comments` only (REQ-006)
- [ ] `core/pack/requirements.py` imports no write client, verified by the AST test (REQ-006)
- [ ] Fetch failures are recorded as notes, visible without `-v`; the module does not import `reviewer.log` (REQ-010)
- [ ] `tests/test_requirements.py` moves under `tests/core/pack/` and uses the fake (REQ-025)
- [ ] Goldens are byte-identical including `ctx.requirements` (REQ-022)

## Notes
Bots are filtered by **both** `type == "Bot"` and a `[bot]` login suffix. Requirements resolution degrades locally on every GitHub failure so the body always survives — the two `vlog()` sites at `review.py:1992` and `:2002` are two of REQ-010's four leaks.

`tests/test_requirements.py` moves as a whole file, so it is rename-detected.
