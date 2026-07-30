---
verdict: fail
criteria: {INT-AC-OBSERVABLE: fail, INT-REQ-RESOLVES: pass, INT-VERTICAL: pass, INT-COVERAGE: fail, INT-NO-OVERLAP: fail, INT-DAG: pass, INT-MILESTONE: pass, INT-SIZED: fail}
---
# Intake check run 3 — modular refactor backlog (47 cards, REQ-001..REQ-028)

Spec: `docs/superpowers/specs/2026-07-28-modular-refactor-design.md` — 28 requirements, all active.
Proposal: manifest v4 (47 cards) + ACs from `2026-07-28-v2-39-cards.md` as amended by
`2026-07-28-v3-delta-53-cards.md`. Board empty; these 47 cards are the whole board.
`size_limit`: 500 changed lines including tests. Prior runs: `2026-07-28-modular-refactor.md` (run 1),
`-run2.md` (run 2). Run 3 is a driver override of an exhausted `check_budget.intake: 2`.

## Verdict

**fail** — nine blocking findings, concentrated in one root cause and two reconstructed cards.

The shape is right and most of run 2 is genuinely discharged: B1 (REQ-010's fourth leak), B3
(REQ-016's gate inverted into a PR test plan), B4 (`prior_rounds` split three ways, marker-first),
and B5-B8 (the four size breaches) are all cleanly resolved, and `INT-DAG` / `INT-MILESTONE` /
`INT-VERTICAL` / `INT-REQ-RESOLVES` pass on a 47-node graph. The failures are narrower than run 2's:

- **One systematic arithmetic defect.** The v3 delta assigned 781 source lines of test relocation
  onto nine existing cards and left all nine estimates at their v2 values. At 2x for a lifted block
  that is ~1,562 unaccounted changed lines, and it is why five cards breach the ceiling.
- **Run 2's B2 is 97% discharged, not 100%.** Six test blocks and helpers, ~205 source lines, still
  belong to no card, in a document that asserts "Nothing in `tests/` is left unowned".
- **One of the two reconstructed cards should not exist as drawn.** CARD-009 (`core/marker`) is
  right. CARD-033 is a count-filler with no acceptance criteria.

My aggregate is ~17,600 changed lines against 47 x 500 = 23,500, against the manifest's 16,124 —
9% higher overall but very unevenly distributed.

## Criteria

| id | verdict | evidence |
|---|---|---|
| INT-AC-OBSERVABLE | **fail** | ~115 criteria walked with "what would I run to see this?". CARD-002's seven call sites verified exactly correct against `review.py:216,288,291,296,301,314,492`. CARD-033 (manifest:118) has **zero** acceptance criteria in any supplied document; CARD-009 has one, derived from delta:45. Three ACs name modules that do not yet exist at their milestone (advisory A3). |
| INT-REQ-RESOLVES | pass | Every id cited across the 47 cards resolves to a spec heading REQ-001..REQ-028, all `**Status:** active`; no superseded or dangling id. CARD-037/-038 omit REQ-028 from `reqs` while carrying its exemption clause — a `reqs` hygiene gap, not a resolution failure (A2). |
| INT-VERTICAL | pass | Run 1's ruling (`2026-07-28-modular-refactor.md:38-47`) stands and is not re-litigated. The two reconstructed cards introduce no new shape: CARD-009 is an extraction card, CARD-033 a test-conversion card, both already ruled on in runs 1 and 2. Each card remains mergeable alone, verifiable without a model call, and revertible alone. |
| INT-COVERAGE | **fail** | REQ-025 incomplete: TestModuleStem (`tests/test_context.py:1541-1560`), TestDiffFenceWrapping + fixtures (`tests/test_prompting.py:196-308`), TestClipHit (`:2273-2301`), and helpers `make_tree`/`unclosed_fence`/`make_archive` (`test_context.py:16-58`) are owned by no card. All 28 REQs otherwise claimed; REQ-026 on the milestone plan accepted (see below). |
| INT-NO-OVERLAP | **fail** | CARD-033's title claims work already claimed by CARD-031 AC-2, CARD-036 AC-2 and CARD-039 AC-2, with no ACs to draw the boundary (manifest:118 vs :116,:129,:132). `TestSeg` is assigned to CARD-032 by delta:83 while `seg` moves to `core/prompt.py` under CARD-012 by delta:55 — the test and the code it drives are on different cards. `prior_rounds` (run 2's B4) is now cleanly divided across CARD-009/031/040 with no double claim. |
| INT-DAG | pass | 47 nodes, 41 edges walked by hand. Every edge points to a strictly lower-numbered card, so the graph is acyclic by construction; no edge names a non-existent id. Two edges I would have added are advisory only (A5). |
| INT-MILESTONE | pass | 47 cards, each in exactly one milestone: M1 001-005 (5), M2 006-013 (8), M3 014-029 (16), M4 030-034 (5), M5 035-039 (5), M6 040-045 (6), M7 046 (1), M8 047 (1) = 47. No orphan, no duplicate. Milestone ranges are contiguous and ascending and every edge is backward, so no card depends on a later milestone. The eleven cross-milestone edges the manifest lists (:180-183) all re-verified. |
| INT-SIZED | **fail** | Five unwaived breaches: CARD-021 (~714), CARD-042 (~708), CARD-012 (~688), CARD-010 (~576), CARD-032 (~543-581). CARD-041 marginal at ~510. CARD-005 at ~1,650 waived by recorded driver override, independently re-costed at ~1,350-1,700 and endorsed for the third time. Full working below. |

## Requirement coverage

Behaviours derived from the spec before the cards were opened, then mapped:

| REQ | observable behaviour | claimed by |
|---|---|---|
| 001 | `reviewer/` package exists in the specified layout; each named module importable | 006-013, 030, 031, 040-045 |
| 002 | `review.py` is three lines; every `CLAUDE.md`/`README.md` command runs verbatim | 045 (folded from v2 CARD-037) |
| 003 | `SourceTree` Protocol with read/exists/walk/grep; four implementations | 014, 029 |
| 004 | every `pack_*` takes a `SourceTree`; no `root is None` branching; `read()` returns None | 015-028 |
| 005 | `ModelClient` Protocol; panel testable with no network | 032, 034 |
| 006 | `IssueSource` with `issue`/`comments` only; requirements path cannot post | 028 |
| 007 | `build_shared_blocks` has no `lens` parameter (inspect.signature) | 012 |
| 008 | `build_verdict_prompt` cannot carry diff or pack; module imports no pack type | 013 |
| 009 | AST test fails on core→adapters/app/log and adapters→app | 006 |
| 010 | four leak sites de-logged: `parse_target`/die (007), `Accounting.report` (010), `resolve_requirements` x2 (028), emission in app (041) | 007, 010, 028, 041 — **run 2's B1 fully discharged** |
| 011 | `_capped` is the only slicer, assertable by AST; 10,060-case sweep green | 010 |
| 012 | drafts/Renovate never selected (040); posting opt-in (044); no state beyond marker (009, 045); `filter="data"` preserved (029) | 009, 029, 040, 044, 045 |
| 013 | githubkit/httpx/PyJWT/pytest adopted and pinned | 035-039, 046 |
| 014 | no `subprocess` in the auth path | 035 |
| 015 | client choice confirmed against the real API; outcome recorded (adopt / PyGithub / stay) | 038 manual test plan, 039 |
| 016 | cache measurement gates the port; retry ladder pinned | 037 manual test plan |
| 017 | `requirements.txt` / `requirements-dev.txt` split; pytest never in the image | 003, 046 |
| 018 | CI green on every PR; image built; GHCR push on tag | 001, 003, 004 |
| 019 | entrypoint `python3 /app/review.py` | 003 |
| 020 | `doctrine/` present inside the image | 003 |
| 021 | bytecode precompiled; container runs `--read-only` | 003 |
| 022 | golden prompt bytes captured and compared | 005 + 30 downstream ACs |
| 023 | five synthetic self-contained fixtures | 005 |
| 024 | two structural tests ship | 005, 006 |
| 025 | test layout mirrors source; `InMemoryTree` + `RecordingModelClient` | 014, 034 + relocation cards — **incomplete, see blocking F7** |
| 026 | stages independently revertible | milestone plan (accepted, see note) |
| 027 | stale worktree warns, degrades, still packs; label predicate correct | 047 |
| 028 | CI never reaches real GitHub/OpenRouter; JWT verified against a test-generated key pair; two exemptions recorded on their cards | 001-005, 033-036, 039 |

**On REQ-026.** Recording it on the milestone plan rather than a card is **correct and I would not
block it** — "independently revertible" is a property of the layout, and the only card that could
assert it would have to assert something about every other card. But it currently has no observable
form anywhere. Recommend the milestone plan's exit criteria state it testably, e.g. *"each merged
card's PR reverts cleanly on its own without touching another card's files"*, so `/kanban` and
`/retro` can see it; as prose in a manifest footer it is invisible to both.

**On the numbering resolution (driver question 3).** The manifest's resolution in favour of the
"Resulting shape" ranges is **correct in substance for every citation**, but the stated hazard is
itself inaccurate — the delta's citations are not uniformly v2:

| delta finding | cites | actually | verdict |
|---|---|---|---|
| B3 | CARD-029, CARD-030 | v2 (says so explicitly) | manifest correct |
| B4 | CARD-007, CARD-023, CARD-033 | v2 — all three nonsense under new numbering (new 023 = a test conversion, new 033 = adapter tests) | manifest correct: → 009, 031, 040 |
| B2 table | 008,010,011,012,013,018-029,032,041-045 | **new** numbering — 043/045 do not exist in v2, and every row cross-checks against the new titles | manifest correct |
| A2 | CARD-012 (core/prompt), CARD-026 (openrouter) | **mixed and partly wrong**: 012 is new numbering (v2's core/prompt was 011); 026 is neither (v2 openrouter = 024, new = 032) | manifest correct by intent; the number is a typo |
| A5 | CARD-030 (cache threshold), CARD-019 ("coverage no lower") | **wrong in both**: the cached_tokens threshold is the cache measurement = v2 029 → new 037; "coverage no lower" is v2 016 → new 018/019/020, all three children | manifest correct for 037; the restatement must apply to all three children, not just 019 |
| A6 | CARD-033, CARD-044 | mixed: 033 is v2 (= new 040), 044 is new | manifest correct: both carry REQ-012 |

So: the resolution holds, but it holds by reading the parentheticals, not the numbers. **Every AC
amendment must be applied by card title, never by the delta's number**, and the intake skill should
record the v2→v4 mapping on the affected cards. The live trap is B4's "CARD-033" — a card by that
number now exists and is an adapters-layer test card, so a literal reading puts the `prior_rounds`
orchestration AC on the wrong card. It belongs on **CARD-040 `app/select`**.

## The two reconstructed cards (driver question 1)

**CARD-009 `core/marker` — correct on all four counts, with one missing AC.**
Right card: yes. REQ-001's layout names `core/marker.py ~60 MARKER_RE parse/compose, round and SHA
recovery`, and delta B4 ruled the marker owns the substance of `prior_rounds`. v2 bundled it into
CARD-007 at 250 *before* B1 added the `parse_target`/`die` work; splitting is the natural growth and
the delta's own test table leaves slot 009 empty (008=diff, 010=budget, 011=render, 012=prompt,
013=consistency). Correctly scoped: `reqs [001, 012, 022]` — REQ-012 for "no state beyond the marker"
is exactly right, and REQ-022 holds because the prior-review body reaches block 2 of the lens prompt.
Correctly placed: M2, `depends_on [006]`. Correctly sized: my estimate 169 against 150.
**Gap:** `prior_rounds` is dismantled across M2 (parse), M4 (fetch) and M6 (orchestrate), so between
CARD-009 and CARD-040 the old inline parser in `review.py:672-686` coexists with `core/marker.py`.
CARD-009 needs an AC forbidding that: *"`prior_rounds` in `review.py` delegates to `core/marker`; no
second `MARKER_RE` parse exists in the package."* Advisory A1.

**CARD-033 `Adapter tests against the stub server` — wrong card. Blocking (F8, F9).** See findings.

## The three deletions and folds (driver question 2)

**v2 CARD-029 (cache measurement) → PR test plan on CARD-037. Sound, and strictly better.**
Run 2's B3 was that a gate downstream of what it gates cannot gate it. A `## Test plan (manual —
must be completed before merge)` on the porting PR binds *before* merge, which is where REQ-016's
"the port does not land until that measurement passes" actually needs to bind. The four checkboxes
in delta:25-29 are observable (two pasted non-zero readings, a re-run rule, a comparison to Gate 1).
**Discharged.**

**v2 CARD-030 (githubkit confirmation) → PR test plan on CARD-038. REQ-015 still binds.**
The confirmation is now on the card that performs the swap, which is the only place it can honestly
live — you cannot confirm githubkit maps onto App installation auth and the 422 fallback without
attempting it. All three of v2 CARD-030's criteria travel, including the outcome-recording clause
("adopt, fall back to `PyGithub`, or stay hand-rolled on httpx"), so REQ-015's decision-with-a-trigger
survives intact; only the board-mutating third criterion moved to Notes, per A4. **Discharged**, with
one residue: that Note still reads "close CARD-031/032 as superseded", which under the new numbering
is CARD-038/039 — and CARD-038 *is* the card. Reword to "if the fallback is taken, CARD-039 is closed
as superseded and this card's scope becomes the fallback implementation." Advisory A4.

**v2 CARD-037 (`review.py` shim) → folded into CARD-045. REQ-002's obligation survives.**
`reqs` on CARD-045 is `[001, 002, 012, 025]`, so impact analysis can see REQ-002, and my size estimate
(~430) confirms the fold fits: 470 was the manifest's figure and the card is not near the ceiling even
after adding the TestResolvePost/TestResolveCache block. The fold is also structurally sound — the
shim cannot be written until `app/cli:main` exists, so a separate card would have been a one-AC card
depending on its own predecessor. **Condition:** all three of v2 CARD-037's ACs must travel verbatim
onto CARD-045 alongside v2 CARD-036's cli half — *"`review.py` is three lines"*, *"every command in
`CLAUDE.md` and `README.md` runs unchanged"*, and *"no module introduces persistence; round number and
last-reviewed SHA come only from `MARKER_RE`"*. The manifest asserts "REQ-002 rides on CARD-045" but
does not restate them, and a fold is exactly where an AC goes missing.

## Size

Method (`_method.md` appendix): a block lifted out of a large file counts twice — deleted from the
source, added to the destination, no rename detection. A whole file that moves counts ~20-40. A test
*conversion* counts twice for the same reason plus rewriting. Line ranges below are real, taken from
`review.py` (2,577 lines) and `tests/` (test_context.py 2,304, test_prompting.py 573, test_diff.py
240, test_requirements.py 226). `size_exclude` removes only `tests/goldens/**`; fixture diffs and the
synthetic source tree are **not** excluded, which is why CARD-005 is large.

| card | mine | theirs | working |
|---|---|---|---|
| CARD-001 | 60 | 60 | new `ci.yml` ~50 |
| CARD-002 | 340 | 420 | env-default edit ~10 (the seven call sites cited are exact); stub server + canned corpus ~200; end-to-end offline test ~120 |
| CARD-003 | 165 | 190 | Dockerfile 30, .dockerignore 10, requirements 13, ci.yml +50, smoke script 60 |
| CARD-004 | 70 | 70 | `release.yml` |
| CARD-005 | 1,350-1,700 | **1,650** | 5 fixture diffs + synthetic tree ~900; harness ~250; regenerate CLI ~80; test ~120. **Waived — driver override, `right_sized: true`.** Third independent costing to land within 3%. |
| CARD-006 | 300 | 310 | DEFAULTS :76-94 (19) x2 + resolution 40; log :98-115 (18) x2; ports stub 15; AST boundary test 150 |
| CARD-007 | 242 | 180 | parse_target :650-658 (9) x2 + raise rework 20 + caller catch 10; schemas :559-625 (67) x2 = 134; new tests 40 |
| CARD-008 | 332 | 420 | _strip_prefix/_hunks/diff_paths/diff_anchors/anchor_violations/diff_size = 136 x2 = 272; `test_diff.py` whole-file rename ~30 |
| CARD-009 | 169 | 150 | MARKER_RE :64-75 (12) x2; new parse/compose 50; delegation 25; new tests 70 |
| CARD-010 | **576** | 400 | code 136 x2 = 272; Accounting→data 40; tests :61-182 (122) x2 = 244 |
| CARD-011 | 306 | 250 | path_matches/is_binary/merge_ranges/windowed = 56 x2 = 112; tests :683-769 (87) x2 = 174 |
| CARD-012 | **688** | 400 | code 80 x2 = 160; block split 80; TestLensPromptBlocks (82) x2 = 164; TestSeg (19) x2 = 38; **TestDiffFenceWrapping + fixtures (113) x2 = 226** |
| CARD-013 | 392 | 320 | consistency + verdict-prompt module ~90 x2 = 140; TestAdjudicatePrompt (106) x2 = 212; I4 mutation tests 40 |
| CARD-014 | 410 | 440 | all new: port 30, LocalTree 140, EmptyTree 30, InMemoryTree 60, tests 150 |
| CARD-015 | 304 | 330 | read_source/_whole_file_body/_file_body/_file_tiers = 77 x2 = 154; port rewrite 60; test updates 90 |
| CARD-016 | 458 | 400 | pack_changed_files less trailer (~180) + _stretch (29) = 209 x2 = 418; rewrite 40 |
| CARD-017 | 108 | 110 | _trailer_groups (24) + trailer rendering (~30) x2 |
| CARD-018 | 300 | 400 | inclusion/skipping ~150 x2 |
| CARD-019 | 560 | 400 | budget/utilisation sweeps ~280 x2 — over only if the delta's stated 150/280/170 division holds; the cut point is choosable, so advisory not blocking (A6) |
| CARD-020 | 340 | 400 | trailer/labelling/file-cap ~170 x2 |
| CARD-021 | **714** | 440 | code 212 x2 = 424; rewrite 60; TestChangedSymbols (66) x2 = 132; **TestModuleStem (20) x2 = 40; TestClipHit (29) x2 = 58** |
| CARD-022 | 210 | 215 | TestGrepRepo :1436-1540 (105) x2 |
| CARD-023 | 334 | 350 | TestPackCallSites + Determinism :1561-1727 (167) x2 |
| CARD-024 | 456 | 455 | pack_conventions (135) + pack_tree (45) + _fence (18) = 198 x2 = 396; rewrite 60 |
| CARD-025 | 330 | 330 | TestPackConventions part A ~165 x2 |
| CARD-026 | 282 | 300 | TestPackConventions part B ~141 x2 |
| CARD-027 | 478 | 480 | TestPackTree (139) + TestFenceBalance (100) = 239 x2. **96% of ceiling** — adding `unclosed_fence` (25) tips it over (A7) |
| CARD-028 | 297 | 330 | issue_refs + resolve_requirements = 56 x2 = 112; IssueSource 25; vlog→notes 40; `test_requirements.py` rename 30 + fake conversion 90 |
| CARD-029 | 462 | 380 | stream_capped/extract_checkout/fetch_checkout = 61 x2 = 122; ApiTree 100; TarballTree 60; tests :183-252 (70) x2 = 140 |
| CARD-030 | 368 | 290 | load_dotenv/Doctrine/resolve_token/_b64u/_app_jwt = 154 x2 = 308; new tests 60 |
| CARD-031 | 472 | 330 | _http/GitHub/whoami/repo_config/post_review/describe_key ~191 x2 = 382; 422 stub test 60; prior-review-body fetch 30. **94% of ceiling** |
| CARD-032 | **543-581** | 434 | code 188 x2 = 376; ModelClient 25; tests :18-108 (90) x2 = 180 |
| CARD-033 | n/a | 250 | **cannot be sized — no acceptance criteria.** Re-scoped as the openrouter test sibling: ~150-180 |
| CARD-034 | 230 | 210 | RecordingModelClient 80; new panel tests 150 |
| CARD-035 | 185 | 200 | delete _b64u/_app_jwt (39); PyJWT signing 25; key-pair JWT test 80 |
| CARD-036 | 300 | 320 | httpx client 60; GitHub method updates 60; stub tests 120 |
| CARD-037 | 220 | 260 | transport call + exception type 40; retry-ladder test 80; shape test 60; manual plan 0 |
| CARD-038 | 310 | 320 | read-path rewrite 150; tests 150 |
| CARD-039 | 290 | 300 | post_review rewrite 80; 422 fallback 60; tests 150 |
| CARD-040 | 306 | 300 | select :691-768 (78) + prior_rounds orchestration (15) = 93 x2 = 186; rework 40; new tests 80 |
| CARD-041 | **510** | 460 | Context (29) + build_context (91) + _checkout_matches_diff (44) = 164 x2 = 328; diagnostics 50; share of TestBuildContext 132 |
| CARD-042 | **708** | 440 | TestBuildContext remainder ~228 x2 = 456; TestCheckoutMatchesDiff (126) x2 = 252 |
| CARD-043 | 472 | 280 | dispatch_lenses/run_panel/run_lens/adjudicate = 125 x2 = 250; TestDispatchLenses (91) x2 = 182; wiring 40. **94% of ceiling** |
| CARD-044 | 286 | 250 | review_pr (43) + review_diff_file (35) = 78 x2 = 156; wiring 50; tests 80 |
| CARD-045 | 430 | 470 | build_parser/resolve_post/resolve_cache/main = 133 x2 = 266; tests :416-482 (67) x2 = 134; shim 10; docs 20 |
| CARD-046 | 195 | 200 | conftest.py 120; runner churn 60; deps + CI 15 |
| CARD-047 | 210 | 230 | head predicate 40; note 20; label logic 30; tests 80; goldens excluded |

**Aggregate ~17,600 against 23,500.** Median ~330. Breaches: CARD-021, CARD-042, CARD-012, CARD-010,
CARD-032. Marginal (>90% of ceiling, no headroom for an unowned block): CARD-041, CARD-027, CARD-031,
CARD-043. Waived: CARD-005.

**Excluded paths applied:** `tests/goldens/**` (CARD-005's goldens only). No `*.lock`, `vendor/**`,
`node_modules/**` or `docs/cards/**` content appears in any card's scope.

## Blocking findings

**F1 — the estimates were not re-derived after the delta changed nine cards' scope.**
`manifest:46-51` / delta B2 table. 781 source lines of test relocation assigned to CARD-010 (+122),
CARD-011 (+87), CARD-012 (+82), CARD-013 (+106), CARD-021 (+66), CARD-029 (+70), CARD-032 (+90),
CARD-043 (+91), CARD-045 (+67), all nine keeping their v2 estimate. At 2x that is ~1,562 changed
lines charged to nobody, and it is the cause of F2-F6. The delta *did* apply 2x to the blocks it
turned into their own cards (215 for 105 lines, 350 for 167, 480 for 239), so the method is
understood — it was simply not applied to blocks folded onto existing cards.
*Remedy:* re-estimate all nine as (code x2) + (test block x2) + rework; never carry a v2 number onto
a card whose scope changed.

**F2 — CARD-021 ~714** (manifest:98). Working above. *Remedy:* split symbol extraction from the grep
half, and place the two unowned blocks on the matching halves.

**F3 — CARD-041/CARD-042 do not fit in two cards** (manifest:145-146); CARD-042 alone ~708.
*Remedy:* three cards — code (~380), TestBuildContext conversion, TestCheckoutMatchesDiff conversion.

**F4 — CARD-012 ~688 once TestDiffFenceWrapping is owned** (manifest:81). That block pins the
diff-fence wrapping invariant `CLAUDE.md` documents; it cannot stay in `tests/test_prompting.py`
while `build_lens_prompt` moves to `core/prompt.py`. *Remedy:* sibling test card.

**F5 — CARD-010 ~576** (manifest:79). *Remedy:* sibling test card for the 122-line budget/accounting
block, leaving code + REQ-010 rework at ~330.

**F6 — CARD-032 ~543-581** (manifest:117). *Remedy:* sibling test card — this is what M4's fifth slot
should hold.

**F7 — six test blocks and helpers remain unowned; run 2's B2 is not fully discharged**
(delta:89, "Nothing in `tests/` is left unowned"). TestModuleStem (`test_context.py:1541-1560`),
TestDiffFenceWrapping + its four fence fixtures (`test_prompting.py:196-308`), TestClipHit
(`:2273-2301`), `make_tree`/`unclosed_fence`/`make_archive` (`test_context.py:16-58`). ~205 source
lines. `unclosed_fence` is a *deliberate independent reimplementation* of `_open_fence` (its docstring
says so) and must travel with CARD-027's fence-balance tests, not be deduplicated against the core
module. *Remedy:* add all six rows to the ownership table.

**F8 — CARD-033 has no acceptance criteria and exists to satisfy a count** (manifest:118, :42-44).
Its stated derivation — mirroring "the delta's own code/test split pattern used six times elsewhere"
— does not hold: v2 CARD-023 is not among the delta's six documented splits. The card M4 actually
needs is the one the delta's own rule requires and did not apply to CARD-032.
*Remedy:* re-scope as the openrouter test sibling (TestCompletionPayload/TestStripFence, ~150-180,
`depends_on [032]`), or delete it and let M4 hold four cards.

**F9 — CARD-033 overlaps CARD-031/036/039** (manifest:118 vs :116, :129, :132). Resolved by F8's
remedy.

## Advisory findings

- **A1** — CARD-009 needs an AC that `review.py`'s `prior_rounds` delegates to `core/marker`
  immediately, so no second `MARKER_RE` parser exists across the two-milestone window before
  CARD-040 lands.
- **A2** — CARD-037 and CARD-038 carry REQ-028's exemption clause in their manual test plans but omit
  REQ-028 from `reqs`. This is precisely run 2's A6 defect class, which the manifest claims to have
  systematically corrected (`manifest:46-51`). Add REQ-028 to both. Similarly CARD-014 delivers
  `InMemoryTree`, one of REQ-025's two named fakes, with `reqs: [003]`.
- **A3** — three ACs name modules that do not exist at their milestone: B1's remedy text puts the
  `parse_target` exception conversion in `app/cli.py` (CARD-007, M2 — `app/cli.py` arrives in CARD-045,
  M6), and v2 CARD-009's AC-2 says "`app/` emits it" for `Accounting.report()` (CARD-010, M2). Reword
  to "the entry point in `review.py`", with CARD-045 carrying it into `app/cli.py`. The substance is
  fine; only the module name is premature.
- **A4** — CARD-038's Note (from the delta's A4 fix) still reads "close CARD-031/032 as superseded",
  which under the new numbering is CARD-038/039 — and CARD-038 is now the card itself. Reword to name
  CARD-039 only.
- **A5** — two `depends_on` edges I would have added: CARD-032→CARD-012 (CARD-032 must leave `seg` and
  `_blocks` behind for `core/prompt.py`; nothing currently orders them), and CARD-034→CARD-043 or an
  explicit disclaimer, since CARD-034's "staggered dispatch tested with no network" and CARD-043's
  relocation of `TestDispatchLenses` both cover staggering.
- **A6** — the delta's three-way division of `TestPackChangedFiles` (150/280/170) makes CARD-019 ~560
  while CARD-018 and CARD-020 come in at 300 and 340. The manifest evened all three to 400, which is
  the right total; the *cut points* need moving to match, since the middle child as described breaches.
- **A7** — four cards sit above 90% of the ceiling with no headroom for the F7 blocks: CARD-027 (478),
  CARD-031 (472), CARD-043 (472), CARD-041 (510). Assigning any unowned block to these tips them over.
- **A8** — REQ-012 still has four invariants asserted by no acceptance criterion anywhere: "only four
  steps call a model", "each model call names its own model", "one failing PR must not abort a pass",
  "v1 is review-only". The third is the one a refactor could plausibly erode, in CARD-045's `main`.
  Consider one AC on CARD-045 and one on CARD-043.
- **A9** — REQ-026 on the milestone plan is the right call, but give it an observable form in the
  milestone exit criteria rather than manifest prose (see Requirement coverage above).

## Spec observations (not card findings)

None this run. All three of run 2's spec defects (REQ-016's incomplete amendment, REQ-010's
miscount, REQ-028's single exemption) are corrected in the spec at `a490c1a` and verified here:
REQ-010 now names four sites and flags `die` explicitly (`spec:255-257`), REQ-028 names two
exemptions (`spec:422-425`), and REQ-016's *Out of scope* entry now reads "its transport call *is*
ported to httpx under REQ-016's measurement gate" (`spec:528-530`).

## Knowledge for `KNOWLEDGE.md`

- When a rework assigns previously-unowned work onto existing cards, every receiving card's estimate
  must be re-derived — not carried over. The v3 delta moved 781 source lines of test relocation onto
  nine cards and left all nine estimates at their prior values, hiding ~1,562 changed lines and
  producing five ceiling breaches. Re-estimating is part of applying the finding, not a follow-up.
- A test-ownership table that claims completeness must be verified against the file, not against
  itself. The v3 delta's table asserted "nothing in tests/ is left unowned" while three blocks fell
  into the gaps between its own cited line ranges (TestModuleStem at `test_context.py:1541-1560`,
  TestDiffFenceWrapping at `test_prompting.py:196-308`, TestClipHit at `:2273-2301`) and three shared
  helpers at `test_context.py:16-58` were never listed. Walk the class list and check that consecutive
  rows abut.
- Never create a card to make a milestone count match. CARD-033 was reconstructed solely because a
  range said M4 held five cards; it arrived with no acceptance criteria and duplicated three other
  cards' stub-server work, while the card the count actually implied — the sibling test card the
  delta's own ceiling rule demanded for CARD-032 — went unwritten. If a count and the documented
  splits disagree, re-derive from the splits.
- Apply cross-document card amendments by title, never by number. The v3 delta mixed three numbering
  systems within one file — B3/B4 cite v2 ids, the B2 table cites new ids, and A2/A5 cite ids valid in
  neither. The substance was recoverable only from the parenthetical titles. The live trap: B4's
  "CARD-033" means `app/select`, but a card numbered 033 now exists and is an adapters-layer test card.
