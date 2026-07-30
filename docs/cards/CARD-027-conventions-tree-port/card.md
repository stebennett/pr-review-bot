---
id: CARD-027
type: task
layer: core
reqs: [REQ-004, REQ-022]
title: pack/conventions and pack/tree against the port
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
estimated_lines: 456
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
Repo conventions and the path tree are the two pack sections that read files nobody changed, so they are the two most dependent on a tree implementation that can walk.

## Acceptance criteria
- [ ] `pack_conventions` and `pack_tree` take a `SourceTree` with no `root is None` branching (REQ-004)
- [ ] Nearest-first convention ordering is unchanged (REQ-004)
- [ ] Goldens are byte-identical on the adversarial-fence fixture (REQ-022)

## Notes
Conventions are ordered nearest-first by distance to a changed directory, so a budget squeeze drops the least specific guidance. Each document is wrapped in a fence sized one backtick longer than any run inside it, so its own headings cannot be mistaken for prompt structure.

`pack_tree` deliberately does **not** reuse `walk_source`: that walk is restricted to `CODE_SUFFIXES` for the grep's benefit, which would drop `README.md`, `Makefile` and every config file from a listing whose whole purpose is 'what does this repo already have'.
