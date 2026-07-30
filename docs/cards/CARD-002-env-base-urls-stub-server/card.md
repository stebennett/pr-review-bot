---
id: CARD-002
type: task
layer: adapters
reqs: [REQ-028]
title: Base URLs default from the environment, with a stub server for tests
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-001]
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
estimated_lines: 340
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
REQ-028 forbids CI from ever reaching the real GitHub or OpenRouter. Stubbing at the transport boundary rather than by injecting in-process fakes keeps the real HTTP client, the real auth path and the real retry ladder under test — which is the only thing that makes the later image smoke-test worth running.

## Acceptance criteria
- [ ] `GITHUB_API` and `OPENROUTER_API` default from environment variables, preserving today's values (REQ-028)
- [ ] All seven call sites (`review.py:216, 288, 291, 296, 301, 314, 492`) resolve through them (REQ-028)
- [ ] A stub HTTP server fixture serves canned GitHub and OpenRouter responses (REQ-028)
- [ ] A test drives a full offline review against the stub with no real network call (REQ-028)

## Notes
The canned-response corpus must cover the installations-token, PR, contents, tarball, issues, comments and post-review GitHub endpoints, plus an OpenRouter completion shaped to `LENS_SCHEMA` (intake run 2, finding A1). The seven call sites above were verified exact by intake run 3.
