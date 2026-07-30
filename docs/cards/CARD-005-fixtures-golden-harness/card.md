---
id: CARD-005
type: task
layer: infra
reqs: [REQ-022, REQ-023, REQ-024, REQ-028]
title: Synthetic fixtures and the golden prompt-byte harness
status: backlog
phase: backlog
right_sized: true
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
estimated_lines: 1650
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
For a refactor, pinning assembled prompt bytes is a stronger claim than pinning findings: findings are stochastic, prompt bytes are not, and identical bytes mean identical model behaviour by construction. Prompt assembly and `build_context` both run entirely offline, so this net costs zero model calls and no money. Every downstream 'goldens byte-identical' criterion anchors here.

## Acceptance criteria
- [ ] The harness runs green against the first fixture before the remaining four are added (REQ-024)
- [ ] Five committed fixtures cover budget-filling, hunk windowing, the dropped-file trailer, adversarial backtick fences, and an all-new-files PR (REQ-023)
- [ ] Goldens record, byte for byte, three lens system+user blocks, the verdict prompt, and `ctx.pack`/`ctx.notes`/`ctx.requirements` (REQ-022)
- [ ] A test regenerates and fails on any byte difference (REQ-024)
- [ ] The harness makes zero network calls and no fixture depends on anything outside the repository (REQ-023, REQ-028)

## Notes
**Driver override, recorded.** This card is ~1,650 counted lines against a 500 ceiling and is deliberately kept whole, `right_sized: true` so the slice phase does not re-split it. Goldens themselves are excluded from the count via `tests/goldens/**`.

The reason is not that the parts are useless apart — a harness plus one fixture is a complete working unit. It is that **the fixture source tree is shared and `pack_tree` renders the whole tree into every fixture's pack**, so a later card adding tree files would move goldens an earlier card established, churning the net during the exact window it is being built.

Independently costed at ~1,600 by intake run 2 and re-endorsed by runs 3 and 4. It is the only card on this board whose estimate is never re-derived before its code is written, because `right_sized: true` means this was its only pre-code size check.
