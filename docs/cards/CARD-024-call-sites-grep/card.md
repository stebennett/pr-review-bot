---
id: CARD-024
type: task
layer: core
reqs: [REQ-004, REQ-022, REQ-025]
title: pack/call_sites — grep and assembly against the port
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-023]
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
estimated_lines: 334
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The grep half is where the port actually earns its keep: `walk_source` and `grep_repo` are the two operations a degraded tree cannot serve, and today that is expressed as `root is None` branching inside the assembler.

## Acceptance criteria
- [ ] `walk_source`, `_clip_hit`, `grep_repo` and `pack_call_sites` take a `SourceTree` (REQ-004)
- [ ] No `root is None` branching remains in them — `review.py:1484` is gone (REQ-004)
- [ ] The `CODE_SUFFIXES` restriction is unchanged (REQ-004)
- [ ] `TestClipHit` (`tests/test_context.py:2273-2301`) moves with `_clip_hit` (REQ-025)
- [ ] Goldens are byte-identical (REQ-022)

## Notes
Completes `core/pack/call_sites.py` so the module ends up exactly as REQ-001 draws it, reached in two steps.

The grep corpus is restricted to a `CODE_SUFFIXES` allowlist, so a repo whose code uses an unlisted extension gets nothing here — and silence is indistinguishable from 'no callers'. That is existing behaviour and must not change.
