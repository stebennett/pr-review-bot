---
id: CARD-041
type: task
layer: adapters
reqs: [REQ-013, REQ-016, REQ-028]
title: Port the OpenRouter transport to httpx
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-036, CARD-040]
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
estimated_lines: 220
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
`adapters/openrouter.py` carries the machinery behind the measured 0.93x cost figure, and it fails silently: a wrong request shape does not error, it stops caching and doubles the bill. So the transport is ported deliberately rather than exempted — and gated on measurement rather than inspection.

## Acceptance criteria
- [ ] `_http` is gone from the package (REQ-013)
- [ ] A test pins three retry attempts on the same status codes as today (REQ-016)
- [ ] Request shape is byte-identical: `cache_control` blocks, `provider.require_parameters`, `cached_tokens` logging (REQ-016)

## Test plan (manual — must be completed before merge)
- [ ] Live run against the real OpenRouter API records `cached_tokens` on lens calls 2 and 3
- [ ] Both readings are non-zero and pasted into this PR
- [ ] If either reads zero, re-run before concluding — OpenRouter routes the same model to different providers call to call, so one zero proves nothing
- [ ] Reading is consistent with Gate 1's 91% cache-read figure

## Notes
Edits only the transport call (`review.py:492`) and its exception type (`:493`). The OpenAI SDK is still not adopted, and nothing else about the module changes.

This is one of exactly two REQ-028 exemptions — inherently live, never a CI job. It is a PR test plan rather than a separate card because `depends_on` means 'after', so a measurement card downstream of the port it gates could never gate it.
