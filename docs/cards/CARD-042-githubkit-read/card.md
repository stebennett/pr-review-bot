---
id: CARD-042
type: task
layer: adapters
reqs: [REQ-013, REQ-015, REQ-028]
title: Swap the GitHub read path to githubkit
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-040]
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
estimated_lines: 310
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
`githubkit` is a typed client with native GitHub App auth, which is most of what `adapters/auth.py` hand-rolls today. Whether it maps cleanly onto App installation auth and the 422 fallback can only be established by attempting it, so the confirmation rides on the card that does the swap.

## Acceptance criteria
- [ ] PR fetch, issue fetch and comment fetch go through the client (REQ-013)
- [ ] Bot filtering by `type == "Bot"` and the `[bot]` login suffix is unchanged (REQ-015)

## Test plan (manual — must be completed before merge)
- [ ] `githubkit`'s App installation auth is verified against the real GitHub API
- [ ] The 422 inline-comment handling is verified against the real API
- [ ] The outcome is recorded on this PR: adopt, fall back to `PyGithub`, or stay hand-rolled on httpx

## Notes
The second of exactly two REQ-028 exemptions. If the fallback is taken, CARD-043 is closed as superseded and this card's scope becomes the fallback implementation — recorded here rather than as an acceptance criterion, because a card cannot close other cards.

This is a decision with a documented trigger, not an open question: `githubkit` is intended, `PyGithub` is the fallback, and staying hand-rolled on httpx is the floor.
