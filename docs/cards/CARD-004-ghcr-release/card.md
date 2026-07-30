---
id: CARD-004
type: task
layer: infra
reqs: [REQ-018, REQ-028]
title: Publish the image to GHCR on a tagged release
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-003]
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
estimated_lines: 70
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The cluster already runs `ghcr.io/stebennett/slack-invite-mgr-{web,backend}` built by that repository's own `release.yml`, with Renovate watching image tags. Publishing here follows an established pattern rather than introducing one.

## Acceptance criteria
- [ ] `release.yml` pushes `ghcr.io/stebennett/pr-review-bot:X.Y.Z` on a version tag (REQ-018)
- [ ] The published image passes the same hermetic smoke-test CI runs (REQ-018, REQ-028)

## Notes
None yet.
