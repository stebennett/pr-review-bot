---
id: CARD-015
type: task
layer: core
reqs: [REQ-001, REQ-008, REQ-025]
title: Extract core/consistency; the adjudicator cannot see the diff or pack
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-013]
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
estimated_lines: 392
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The adjudicator never sees the diff and never sees the pack. That is structural, not stylistic — the design depends on it. Giving `build_verdict_prompt` no parameter capable of carrying either, in a module that imports no pack type, replaces a convention with a guarantee.

## Acceptance criteria
- [ ] `build_verdict_prompt` has no parameter able to carry the diff or the pack, verified by `inspect.signature` (REQ-008)
- [ ] Its module imports no pack type, verified by the AST test (REQ-008)
- [ ] The I4 mutation tests still fail when the diff or the pack is appended via `run_panel` (REQ-008)
- [ ] `TestAdjudicatePrompt` (`tests/test_prompting.py:309-414`) and the `flat` fixture (`:306-308`) move under `tests/core/` (REQ-025)

## Notes
The resolved requirements string is the one deliberate exception to the adjudicator's blindness: it reaches the verdict exactly as the plain PR body did before, so the verdict can judge conformity claims against what was actually asked. Keep it faithful to what humans wrote and add no framing — an earlier version injected 'Requirements as stated by people, not by the description', which asserted a priority nobody wrote, and was removed for that reason.

`doctrine/agents/pr-review-verdict.md` explains why the blindness matters. Never add the diff or `ctx.pack` to that prompt.
