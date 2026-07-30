---
id: CARD-003
type: task
layer: infra
reqs: [REQ-017, REQ-018, REQ-019, REQ-020, REQ-021, REQ-028]
title: Container image, built and hermetically smoke-tested on every PR
status: backlog
phase: backlog
right_sized: ""
depends_on: [CARD-002]
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
estimated_lines: 165
actual_lines: ""
started: ""
delivered: ""
created: 2026-07-30
---

## Why
The Kubernetes deployment does not deploy this repository — it deploys a hand-copied 999-line duplicate. Under a modular layout, shipping without an image means a manual cross-repo file copy per module, with an `ImportError` killing every review on any miss. This card closes that gap.

## Acceptance criteria
- [ ] `Dockerfile` produces an image whose entrypoint is `python3 /app/review.py` (REQ-019)
- [ ] `doctrine/` is present inside the image (REQ-020)
- [ ] Bytecode is precompiled at build; the container runs with `--read-only` (REQ-021)
- [ ] `requirements.txt` and `requirements-dev.txt` exist; no dev dependency is in the image (REQ-017)
- [ ] CI builds the image and runs a full review against the stub server, not `--help` (REQ-018, REQ-028)

## Notes
The entrypoint stays `/app/review.py` so `home-lab-k8s`'s `cronjob.yaml` `command:` needs no edit — the eventual deployment change is swapping a ConfigMap volume for an `image:`. That change is out of scope here and belongs to the driver.

`COPY` must not name individual directories: every milestone that adds one would need a Dockerfile edit, and a missed one reintroduces exactly the silent-omission failure the ConfigMap had.
