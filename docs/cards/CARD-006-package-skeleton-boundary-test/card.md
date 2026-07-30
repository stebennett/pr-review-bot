---
id: CARD-006
type: task
layer: core
reqs: [REQ-001, REQ-009, REQ-022, REQ-024]
title: Package skeleton, config, log, ports, and the import-boundary test
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-005]
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
estimated_lines: 300
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The import-boundary test is what keeps the 'pure core' claim true over time. Landing it before any code moves means every later extraction is checked as it happens, rather than audited afterwards.

## Acceptance criteria
- [ ] `reviewer/config.py` holds `DEFAULTS` and pure resolution with no `.env` side effect (REQ-001)
- [ ] An AST test fails if `core/` imports `adapters`, `app` or `log`, or `adapters/` imports `app` (REQ-009)
- [ ] CI runs the import-boundary test (REQ-024)
- [ ] Goldens are byte-identical (REQ-022)

## Notes
`reviewer.config` is on `core/`'s permitted import list because it is reduced to `DEFAULTS` and pure resolution over a dict; `.env` loading — its one side effect today — moves to `adapters/env.py` in CARD-034.
