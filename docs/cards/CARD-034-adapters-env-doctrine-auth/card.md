---
id: CARD-034
type: task
layer: adapters
reqs: [REQ-001]
title: Extract adapters/env, adapters/doctrine, adapters/auth
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
estimated_lines: 338
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
`.env` loading is the one side effect `config.py` performs today, and it is why `config.py` could not otherwise be on `core/`'s permitted import list. Moving it, doctrine loading and token resolution to the edge is what makes the earlier boundary claim honest.

## Acceptance criteria
- [ ] `.env` loading lives in `adapters/env.py`, not `config.py` (REQ-001)
- [ ] `Doctrine` loading and token resolution live in `adapters/` (REQ-001)

## Notes
Auth resolves GitHub App → `GH_TOKEN`/`GITHUB_TOKEN` → `gh auth token`, in that order. `openssl` is still shelled out to for JWT signing at this point; CARD-039 deletes that.
