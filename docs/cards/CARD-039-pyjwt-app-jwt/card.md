---
id: CARD-039
type: task
layer: adapters
reqs: [REQ-013, REQ-014, REQ-028]
title: Sign App JWTs with PyJWT; delete the openssl shell-out
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-034]
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
estimated_lines: 185
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The `openssl` shell-out is a binary dependency on the base image that exists only because PyPI was unavailable. A container has an install step, so it can go — and removing a subprocess from the auth path is a standalone win that stands whatever happens to the client swap later.

## Acceptance criteria
- [ ] No `subprocess` call remains in the auth path (REQ-014)
- [ ] The JWT verifies against a key pair generated in the test, asserting `iss`, `iat`, `exp` and `alg=RS256` (REQ-028)
- [ ] `PyJWT` and `cryptography` are pinned in `requirements.txt` (REQ-013)

## Notes
Verifying against a locally generated key pair is a **stricter** assertion than a live call: it can check `iss`, `iat`, `exp` and `alg`, where a live call only proves the token was accepted.

CARD-042 may later delegate the same work to `githubkit`'s own installation-auth strategy, superseding most of this card's code. That is expected, not waste — this removes the shell-out immediately and independently of whether the client swap survives its verification.
