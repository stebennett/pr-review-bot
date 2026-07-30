---
id: CARD-001
type: task
layer: infra
reqs: [REQ-018, REQ-028]
title: CI runs the test suite on every pull request
status: backlog
phase: backlog
right_sized: ""
depends_on: []
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
estimated_lines: 60
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
Every later card in this refactor is validated by the 263-test suite. Until CI runs it on every pull request, that validation depends on a human remembering to run it locally, and the whole point of the safety net is that it cannot be forgotten.

## Acceptance criteria
- [ ] `.github/workflows/ci.yml` runs the suite on every PR and reports status (REQ-018)
- [ ] A deliberately failing test shows a red check (REQ-018)
- [ ] The workflow makes no network call to GitHub's or OpenRouter's real APIs (REQ-028)

## Notes
First card on the board. The suite runs with no install step today (`python3 -m unittest discover -s tests -t .`), so this workflow needs no dependency resolution yet — `requirements-dev.txt` arrives in CARD-003.
