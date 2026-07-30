---
id: CARD-016
type: task
layer: core
reqs: [REQ-003, REQ-025]
title: SourceTree port, LocalTree, EmptyTree, InMemoryTree
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
estimated_lines: 410
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The context pack defines four acquisition rungs, and today each is expressed as `root is None` / `gh is None` branching scattered across five assemblers. Under a `SourceTree` port each rung is simply which implementation you were handed, and the assemblers stop knowing that degradation exists.

## Acceptance criteria
- [ ] `ports.py` defines `SourceTree` with `read`, `exists`, `walk` and `grep` (REQ-003)
- [ ] `read()` returns `None` rather than raising on any failure (REQ-003)
- [ ] `LocalTree`, `EmptyTree` and an `InMemoryTree` test fake implement it (REQ-003, REQ-025)

## Notes
Owns only the port and the three implementations. `walk_source`, `grep_repo` and `_clip_hit` move in CARD-024; `TarballTree` and `ApiTree` complete the ladder in CARD-033.

`read()` returning `None` rather than raising is what makes 'the pack must never fail a review' enforceable in one place instead of in every assembler.
