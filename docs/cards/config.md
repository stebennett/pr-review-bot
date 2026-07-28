---
spec_path: docs/superpowers/specs/2026-07-28-modular-refactor-design.md
gh_command: gh
board_dir: docs/cards
adr_dir: docs/adrs
kanban_flow_version: "0.10.0"
template_overrides: {}
wip_limit: 3
pump_gate: on
gates:
  slice: auto
  design: pr
  deliver: auto
checks:
  intake: on
  slice: on
  design: on
  split: on
  deliver: on
check_budget:
  intake: 2
  slice: 2
  design: 2
  implement: 2
  split: 1
  deliver: 1
review_panel: full
size_limit: 500
size_exclude:
  - "*.lock"
  - "package-lock.json"
  - "yarn.lock"
  - "pnpm-lock.yaml"
  - "Cargo.lock"
  - "poetry.lock"
  - "uv.lock"
  - "go.sum"
  - "Gemfile.lock"
  - "composer.lock"
  - "vendor/**"
  - "node_modules/**"
  - "docs/cards/**"
  - "tests/goldens/**"
layers:
  - infra
  - core
  - adapters
  - app
gate_layer: core
coverage_target: "90% on reviewer/core"
# testing:                      # OPTIONAL — uncomment to enable test levels. The switch is
#   levels:                     #   `testing.levels` non-empty ("levels configured"). TODO: set commands.
#     integration: { command: "make test-integration", scope: card, needs_env: true }
#     contract:    { command: "make test-contract",    scope: card }
#     functional:  { command: "make test-functional",  scope: card, needs_env: true }
#     journey:     { scope: pr }
#     experience:  { scope: pr }
#   derive:                     # level -> layers that owe it. Defaults cover the conventional
#     integration: [db, api, infra]   # five layers; custom layers MUST supply this map.
#     contract:    [api]
#     functional:  [api, web]
#     journey:     [web]
#     experience:  [web]
#   seams:                      # declared boundaries where fakes are permitted
#     - { name: postgres, kind: database, integration: real }
#   env:                        # required iff any level has needs_env: true
#     up: "make test-env-up"
#     down: "make test-env-down"
#     ready: "make test-env-ready"
#     base_url_env: E2E_BASE_URL
#   journeys:                   # 5-10, product-owned, changed rarely
#     - { id: J1, name: "TODO: first critical user journey" }
#   experience:
#     viewports: [390x844, 1280x800]
#     accessibility: { ruleset: wcag21aa, max_violations: 0 }
#     budgets: { lcp_ms: 2500, cls: 0.1, tbt_ms: 300 }
#     selector_convention: "data-testid"
#   harness_paths: ["tests/harness/**", "tests/factories/**"]
#   quarantine_age_days: 5
#   nightly_main: off           # or: { workflow: nightly.yml }
#   telemetry: { flake_rate_max: 0.02 }   # advisory only — never blocks
---

# kanban-flow configuration

The single source of project-specific tunables. `/kanban-init` creates it;
**`/kanban` never rewrites it**, so it is safe to hand-edit. **Agents never read
this file** — every value an agent needs arrives in its dispatch; only `/kanban`
and the intake skills (`/refine`, `/requirement`, `/kanban-init`, `/migrate`) read it.

- **spec_path** — the requirements doc `/refine` and `card-slicer` read.
- **gh_command** — the GitHub CLI, or a bot-identity wrapper; every `gh`/API call
  goes through it. Default `gh`.
- **board_dir** / **adr_dir** — where the board (cards, templates, this file) and
  ADRs live. Conventional locations (`docs/cards`, `docs/adrs`), hardcoded in most
  places — leave the defaults.
- **kanban_flow_version** — the plugin version this board was last synced to.
  `/kanban-init` stamps it, `/migrate` updates it; `/kanban` compares it to nudge you
  to `/migrate`.
- **template_overrides** — optional map from a template name (`card-template.md` |
  `pr-template.md` | `design-pr-template.md`) to a repo-relative path read instead of
  the plugin's. Empty (`{}`) → plugin templates; `/migrate` sets one for a customized
  template.
- **wip_limit** — max cards in flight at once.
- **pump_gate** — `on` (default; a missing key reads as `on`) runs the cheap
  `pump-gate` haiku agent first each pump (SKILL.md §0.0), so a quiet board under
  `/loop` decides idle-vs-run in a minimal context instead of loading the board.
  `off` bypasses it and runs reconcile directly — a debugging escape hatch, not the
  normal path.
- **gates** — per-gate policy. `slice`: `auto` | `manual`. `design`: `pr` (design PR
  is the review) | `domain` (stop for `gate_layer` cards only) | `manual` (stop every
  card). `deliver`: `auto` | `manual`.
- **checks** — every producer has a checker; every check runs by default. Turning
  one `off` (escape hatch for a noisy checker) makes `/kanban` warn every pump and on
  `BOARD.md` what ships unchecked — `slice: off` in particular removes the pre-code
  **size_limit** cap (`SLC-SIZE`), and `split: off` disables the carve entirely (an
  oversized branch ships as one oversized PR). No `implement` switch exists (tester +
  lens panel are unconditional). Omitted → `on`. (RATIONALE.)
- **check_budget** — per-producer automatic rework loops before a card parks;
  `deliver`/`split` are spent **per PR** (`/kanban` resets the counters at each
  PR/slice boundary). Omitted producer → `2`, except `deliver`/`split` → `1`.
  (RATIONALE.)
- **review_panel** — how many lenses the review panel dispatches (the pump body, §5).
  `full` (default; a missing key reads as `full`) — the whole table: acceptance,
  design, functionality, security, simplicity, tests, readability + the language
  lenses (`python`/`typescript`, when the diff matches). `standard` — acceptance,
  functionality, tests, security + the language lenses. `light` — acceptance,
  functionality + the language lenses. Each reduced tier drops the lenses above it.
  Use `standard`/`light` on low-risk layers watching token spend; keep `full` for
  `gate_layer` cards and anything security-sensitive — such a card under a reduced
  panel is warned in the report. The panel is the costliest phase and lens count is
  its multiplier — the largest token dial. (RATIONALE.)
- **size_limit** — the hard ceiling on a card's **changed lines, including tests**
  (default 500). Enforced at slice (`SLC-SIZE`, blocking — forces a split) and deliver
  (`DLV-SIZE`, advisory — proposes one).
- **size_exclude** — glob paths omitted from both counts: lock files, vendored deps,
  **plus the board (`docs/cards/**`)** so a card's phase docs don't count against it.
  Add generated code (protobuf, OpenAPI); move it with `board_dir`. (RATIONALE.)
- **testing** — optional block enabling test levels (spec:
  `docs/superpowers/specs/2026-07-23-kanban-testing-levels-design.md`). The switch for every new
  obligation is **`testing.levels` present and non-empty** ("levels configured"). Semantics:
  `levels` maps level name → `{command?, scope, needs_env?}`; `scope` required, `card | pr`;
  `scope: card` requires `command`; `scope: pr` takes none; `needs_env: true` wraps the level in
  the `env` lifecycle and requires the `env` block (all four keys). The name `unit` is reserved —
  the existing suite/coverage/property/lint gates own it. `derive` maps each level to the layers
  that owe it; built-in defaults cover the conventional `[infra, domain, db, api, web]` — if
  levels are configured, `derive` is omitted, and `layers` is not a subset of those five, loading
  fails naming the missing map. `seams` lists the boundaries where fakes are permitted (absent →
  seam rules inert, `DSG-SEAMS` verdicts `na`). `journeys` is expected non-empty when a `journey`
  level exists (missing → load warning). `harness_paths` — see the size budget above; works
  without levels. `quarantine_age_days` (default 5) and `nightly_main` (`off` or
  `{workflow: <file>}`) drive the flake/escaped-defect machinery. `telemetry` is advisory only.
  **On any validation error the pump surfaces the exact error in its report and treats levels as
  unconfigured for that pump** — loud and safe, never half-parsed. Agents never read this block;
  values arrive per dispatch.
- **layers** — the architectural layers, **in order** — the scheduler's tie-break
  rank for the next ready card. Tag each card's `layer` with one.
- **gate_layer** — the layer that triggers the `design: domain` stop (riskiest
  rules); usually the pure-logic core.
- **coverage_target** — the test-coverage expectation agents cite.
