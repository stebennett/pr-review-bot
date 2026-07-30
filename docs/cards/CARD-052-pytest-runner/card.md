---
id: CARD-052
type: task
layer: infra
reqs: [REQ-013, REQ-017, REQ-025]
title: Migrate the runner to pytest
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-051]
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
estimated_lines: 195
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
Test relocation already happened card by card, so this is the runner alone — which is why it is additive rather than a rewrite. pytest runs the existing unittest classes unchanged.

## Acceptance criteria
- [ ] The suite runs under pytest with no test lost, and CI runs it (REQ-013)
- [ ] `conftest.py` provides the `InMemoryTree`, `RecordingModelClient` and stub-server fixtures (REQ-025)
- [ ] `pytest` is in `requirements-dev.txt` and absent from the image (REQ-017)

## Notes
**`tests/__init__.py` must exist and stay empty** until `conftest.py` demonstrably replaces its role — `unittest discover -t .` fails without it with `ImportError: Start directory is not importable`. Do not delete it as part of this migration without proving the replacement first.
