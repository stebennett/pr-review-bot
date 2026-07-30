---
id: CARD-036
type: task
layer: adapters
reqs: [REQ-005]
title: Relocate openrouter behind ModelClient
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-006, CARD-013]
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
estimated_lines: 393
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
`ModelClient` is the seam that lets the panel's staggered dispatch, retry ladder and consistency enforcement be tested without a network and without cost. Today none of that logic can be exercised without spending money.

## Acceptance criteria
- [ ] `ports.py` defines `ModelClient` (REQ-005)
- [ ] `completion_payload`, `strip_fence`, `openrouter` and `_Heartbeat` live in `adapters/openrouter.py` behind it (REQ-005)
- [ ] Request shape is unchanged: `cache_control` blocks, `provider.require_parameters`, the retry ladder and `cached_tokens` logging (REQ-005)

## Notes
**Relocation only** — the httpx port is CARD-041.

`seg` and `_blocks` are deliberately **left behind** for `core/prompt.py`; they moved in CARD-013, which is why this card depends on it. If they followed the OpenRouter section into `adapters/`, `build_shared_blocks` could not call them without breaking the boundary test. `strip_fence` correctly comes here, because it parses a model response.

The request shape fails silently: a wrong shape does not error, it simply stops caching and doubles the bill.
