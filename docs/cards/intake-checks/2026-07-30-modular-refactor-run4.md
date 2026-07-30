---
verdict: pass
criteria: {INT-AC-OBSERVABLE: pass, INT-REQ-RESOLVES: pass, INT-VERTICAL: pass, INT-COVERAGE: pass, INT-NO-OVERLAP: pass, INT-DAG: pass, INT-MILESTONE: pass, INT-SIZED: pass}
---
# Intake check run 4 — modular refactor backlog (53 cards, REQ-001..REQ-028)

Spec: `docs/superpowers/specs/2026-07-28-modular-refactor-design.md` at `a490c1a` — 28 requirements,
all `**Status:** active`. Proposal: manifest v5 (53 cards) with ACs from
`intake-proposals/2026-07-28-v2-39-cards.md` as amended by `2026-07-28-v3-delta-53-cards.md`,
**applied by card title** per run 3's ruling. Board empty; these 53 cards are the whole board.
`size_limit`: 500 changed lines including tests. Prior runs: run 1 (`2026-07-28-modular-refactor.md`),
run 2 (`-run2.md`), run 3 (`-run3.md`). Run 4 is the second deliberate driver override of an
exhausted `check_budget.intake: 2`.

## Verdict

**pass** — no blocking finding. All nine of run 3's blocking findings are discharged, and I verified
each against the codebase rather than against the manifest's claim:

- **F1** — every card whose scope the v3 delta changed now carries a re-derived estimate. I re-costed
  all 53 from real line ranges and reconciled each against run 3's working card by card (table below);
  no v2 number survives, and the two split pairs sum to their parent's run-3 figure (010+011 = 576;
  013+014 = 688; 023+024 = 702 vs 714; 036+037 = 571 vs 543-581; 045+046+047+048 = 1,240 vs 1,218).
- **F2, F4, F5, F6** — the four sibling splits are real seams: in each case the code card leaves
  `review.py` re-exporting the moved names, so the unconverted test block stays green until its own
  card lands. Verified for the one the driver flagged: `pack_call_sites` (`review.py:1479-1524`) calls
  `changed_symbols` (:1488) and `_module_stem` (:1503), and `walk_source` (:1425) calls `_suffix` — all
  three moving in CARD-023 — so after CARD-023 `review.py` imports them from
  `core/pack/call_sites.py` and the suite is green with `pack_call_sites` still in place. CARD-024 then
  completes the module and does all the port work. The seam holds, in that order only, which
  `depends_on [023]` gives.
- **F3** — the four-way cut of `app/context` is sound and every child is under the ceiling.
- **F7** — all six formerly-orphaned blocks have correct homes and every receiving card still fits.
- **F8/F9** — the count-filler is gone; CARD-037 has a real, non-overlapping scope
  (test_prompting.py:37-86) and an estimate that matches it.

What remains is nine advisories, five of them one root cause: the ownership record tracks test
*classes* well and shared *fixtures* poorly. Four fixture groups (~77 source lines) are owned by the
wrong card or by none. I did not block on it, and the reasoning is stated under `INT-COVERAGE` — a
mis-homed fixture cannot silently lose coverage, because the relocated test fails to import.

My aggregate is ~17,400 changed lines against 53 x 500 = 26,500, median ~300, against the manifest's
17,386 (which itself sums to 17,486).

## Criteria

| id | verdict | evidence |
|---|---|---|
| INT-AC-OBSERVABLE | pass | ~115 criteria re-walked from v2 as amended by title, each against "what would I run to see this?". Run 3's only failure is fixed: CARD-037 replaces the AC-less CARD-033 with a named block. M6's new REQ-026 exit criterion ("each merged card's PR reverts cleanly on its own without touching another card's files") is observable — `git revert <sha>` on one PR, `git diff --name-only` confined to that card's files. A3 applied ("the entry point in `review.py`"). Seven cards carry no bespoke AC text yet (advisory) — same shape as 020/021/022 and 028/029, which run 3 passed. |
| INT-REQ-RESOLVES | pass | Every id cited across all 53 cards resolves to a spec heading in REQ-001..REQ-028, all `**Status:** active` (spec:87-504); no superseded or dangling id. Run 3's A2 is verifiably applied: CARD-041 `reqs [013,016,028]`, CARD-042 `[013,015,028]`, CARD-016 `[003,025]`. A6 applied: REQ-012 present on 009, 033, 044, 049, 050, 051. One internal inconsistency about which card carries REQ-015's exemption (advisory). |
| INT-VERTICAL | pass | Run 1's ruling (`2026-07-28-modular-refactor.md:38-47`) stands and is not re-litigated. The six new cards introduce no new shape — all are test-conversion cards, a shape run 2 examined and passed. Each remains mergeable alone (review.py re-exports until CARD-051), verifiable without a model call, and revertible alone. One title asserts port work its scope does not contain (CARD-023, advisory). |
| INT-COVERAGE | pass | Behaviours derived from the spec before the cards were opened; map below. All 28 REQs claimed except REQ-026, accepted on M6's exit criteria per A9. REQ-025 re-audited by walking the full class list of all four test files: every test class in `test_context.py` (2,304 lines) and `test_prompting.py` (573) now has exactly one owner and consecutive owners abut. Four shared fixture groups remain mis-homed or unowned (advisory) — `_FakeGH` :253-262, `DIFF`/`PR`, the fence fixtures, `flat`. |
| INT-NO-OVERLAP | pass | No two cards claim the same work. Run 3's two failures are resolved: CARD-033's triple duplication is gone with the card, and TestSeg no longer sits on an adapters card (CARD-037's title scopes it out; CARD-013's 462 retains it) — though only implicitly, hence an advisory. The A/B and three-way test splits (020/021/022, 028/029, 046/047) are themed, not overlapping, at the same granularity run 3 accepted. |
| INT-DAG | pass | 53 nodes, 60 edges walked by hand. Every edge points to a strictly lower-numbered card, so the graph is acyclic by construction; every id names a real proposed sibling. Three edges I would add are advisory (051→046/047/048). A5's missing edge is applied: CARD-036 `depends_on [006, 013]`, so `openrouter` cannot relocate before `core/prompt` claims `seg`/`_blocks`. |
| INT-MILESTONE | pass | 53 cards, each in exactly one milestone: M1 001-005 (5), M2 006-015 (10), M3 016-033 (18), M4 034-038 (5), M5 039-043 (5), M6 044-051 (8), M7 052 (1), M8 053 (1) = 53. Ranges contiguous and ascending; every edge backward, so no card depends on a later milestone. The manifest's cross-milestone enumeration omits 039→034 (M5→M4) — a documentation gap only, the edge itself is legal. |
| INT-SIZED | pass | 53 cards re-costed from real line ranges; **no unwaived breach**, tightest CARD-033 (492), CARD-035 (472), CARD-049 (472), CARD-018 (458). CARD-005 at ~1,650 waived by recorded driver override, `right_sized: true`, independently re-costed at 1,350-1,700 and endorsed for the fourth time. Full working below. Only CARD-005 is `right_sized`, so every other card is re-sized by the slice phase. |

## Requirement coverage

Behaviours derived from the spec before the cards were opened, then mapped to v5 ids:

| REQ | observable behaviour | claimed by |
|---|---|---|
| 001 | `reviewer/` exists in the spec:89-129 layout; every named module importable | 006-015, 034-036, 044-051 |
| 002 | `review.py` is three lines; every `CLAUDE.md`/`README.md` command runs verbatim | 051 |
| 003 | `SourceTree` Protocol with read/exists/walk/grep; four implementations | 016, 033 |
| 004 | every `pack_*` takes a `SourceTree`; no `root is None` branching; `read()` returns None | 017-032 |
| 005 | `ModelClient` Protocol; panel testable with no network | 036, 037, 038 |
| 006 | `IssueSource` with `issue`/`comments` only; requirements path cannot post | 032 |
| 007 | `build_shared_blocks` has no `lens` parameter (inspect.signature) | 013, 014 |
| 008 | `build_verdict_prompt` cannot carry diff or pack; module imports no pack type | 015 |
| 009 | AST test fails on core→adapters/app/log and adapters→app | 006 |
| 010 | four leak sites de-logged: `parse_target`/`die` (007), `Accounting.report` (010), `resolve_requirements` x2 (032), emission in app (045) | 007, 010, 032, 045 |
| 011 | `_capped` is the only slicer, assertable by AST; 10,060-case sweep green | 010, 011 |
| 012 | drafts/Renovate never selected (044); posting opt-in (051); no state beyond the marker (009, 051); `filter="data"` preserved (033); one failing PR does not abort a pass (049/051, A8) | 009, 033, 044, 049, 050, 051 |
| 013 | githubkit/httpx/PyJWT/pytest adopted and pinned | 039-043, 052 |
| 014 | no `subprocess` in the auth path | 039 |
| 015 | client choice confirmed against the real API; outcome recorded (adopt / PyGithub / stay) | 042 manual plan, 043 |
| 016 | cache measurement gates the port; retry ladder pinned | 041 manual plan |
| 017 | `requirements.txt` / `requirements-dev.txt` split; pytest never in the image | 003, 052 |
| 018 | CI green on every PR; image built; GHCR push on tag | 001, 003, 004 |
| 019 | entrypoint `python3 /app/review.py` | 003 |
| 020 | `doctrine/` present inside the image | 003 |
| 021 | bytecode precompiled; container runs `--read-only` | 003 |
| 022 | golden prompt bytes captured and compared | 005 + ~30 downstream ACs |
| 023 | five synthetic self-contained fixtures | 005 |
| 024 | two structural tests ship | 005, 006 |
| 025 | test layout mirrors source; `InMemoryTree` + `RecordingModelClient` | 016, 038 + all 18 relocation cards — every test class owned, four fixture groups advisory |
| 026 | stages independently revertible | M6 exit criterion, now observable |
| 027 | stale worktree warns, degrades, still packs; label predicate correct | 053 |
| 028 | CI never reaches real GitHub/OpenRouter; JWT verified against a test-generated key pair; exactly two exemptions | 001-005, 035, 038-043 |

**Test-file ownership walk (REQ-025), checked for abutment.** `tests/test_context.py`: 16-22 → 048 ·
23-49 → 031 · 50-58 → 033 · 61-182 → 011 · 183-252 → 033 · **253-262 unowned** · 263-556 → 046+047 ·
557-682 → 048 · 683-769 → 012 · 770-1369 → 020+021+022 · 1370-1435 → 023 · 1436-1540 → 025 ·
1541-1560 → 023 · 1561-1727 → 026 · 1728-2033 → 028+029 · 2034-2127 → 030 · **2128-2172 mis-homed
(030's span, 031's tests)** · 2173-2272 → 031 · 2273-2301 → 024. `tests/test_prompting.py`: 18-36 →
013 (implicit) · 37-86 → 037 · **88-106 mis-homed (037's span, 013/014/015's tests)** · 109-190 → 013 ·
196-305 → 014 · **306-308 mis-homed (014's span, 015's tests)** · 309-414 → 015 · 416-482 → 051 ·
483-573 → 049. `tests/test_diff.py` → 008 whole file; `tests/test_requirements.py` → 032 whole file;
`tests/__init__.py` stays and stays empty until 052 proves `conftest.py` replaces it.

## The six new splits (driver question 1)

**CARD-010/011 — real seam.** Code is `budgets`/`Accounting` (:1821-1872), `_capped`/
`_truncation_markers`/`_open_fence` (:796-854) and `_truncate_inline` (:1551-1566) = 127 source lines.
The tests at test_context.py:61-182 address `review.budgets`/`review.Accounting`/
`review._truncate_inline`, so they stay green against the re-export and convert on CARD-011. Titles
match the block exactly ("budget, accounting and inline-truncation" = TestBudgets + TestAccounting +
TestTruncateInline). 332 + 244.

**CARD-013/014 — real seam.** TestDiffFenceWrapping drives `build_lens_prompt`'s diff wrapper, which
CARD-013 moves; the test stays green against the re-export. Its four fixtures (:196-252) travel with
it, which is what F4 asked for. 462 + 226. One wrinkle: CARD-014 imports `unclosed_fence` from
`test_context` (test_prompting.py:15) two milestones before CARD-031 owns it (advisory).

**CARD-023/024 — the seam is real, and this is the answer to the driver's specific doubt.**
`pack_call_sites` needs `changed_symbols` and `_module_stem`, and `walk_source` needs `_suffix` — but
it needs them as *imports*, not as co-located code. After CARD-023 moves the pure symbol half into
`core/pack/call_sites.py`, `review.py`'s `pack_call_sites` imports the three names and the suite is
green with no behaviour change; CARD-024 then moves the grep half into the same module and does the
REQ-004 port work (`if root is None` at :1484 is 024's to delete). The module ends up exactly as
REQ-001 draws it (spec:108). Sizes 368 (mine 370) and 334 (mine 328). The only defect here is the
inherited AC asserting `changed_symbols` takes a `SourceTree`, which it must not (advisory).

**CARD-030/031 — real seam, one mis-homed fixture group.** TestPackTree drives `pack_tree`;
TestFenceBalanceUnderTruncation is a swept property over every section and the assembled prompt, and
is the natural owner of `unclosed_fence`, which run 3 correctly refused to deduplicate against
`_open_fence`. But the four fixtures at :2128-2172 are consumed only by 031 while sitting in 030's
cited span. Neither card breaches either way (030: 188-278; 031: 250-342).

**CARD-045/046/047/048 — the two-way cut of TestBuildContext is a real seam, and both halves fit,
but they are not both 294.** The class is test_context.py:263-556 (294 source lines, 588 changed). The
cut the titles describe falls at :381: config/filesystem degradation is :267-380 (7 methods —
malformed `max_context_chars` x2, read-only filesystem, missing `max_tarball_bytes`, validity check
raising, body exception not swallowed, context disabled) plus `_pr` and `_FakeGH`, ~128 source lines →
~256; pack assembly and notes is :381-556 (6 methods — worktree populates the pack, truncated
conventions fence, and the four worktree-acceptance/degradation-note tests), 176 lines → ~352. Both
well under 500, and the cut point is choosable, so this passes; the 294/294 figures are an even
halving rather than a measured split (advisory). CARD-045's code half is `Context` (:1934-1962),
`build_context` (:2063-2146) and `_checkout_matches_diff` (:2019-2062) = 157 x2 + diagnostics = ~364
against 380. CARD-048 is TestCheckoutMatchesDiff (:557-682) x2 + `make_tree` = ~266 against 272.

**CARD-036/037 — real seam, correct re-scope.** 036 relocates `completion_payload`/`strip_fence`/
`openrouter`/`_Heartbeat` (184 source lines) behind `ModelClient` and, per A5, leaves `seg`/`_blocks`
for `core/prompt` — the edge 036→013 is present. 037 converts test_prompting.py:37-86. Together 571,
against run 3's 543-581 for the unsplit card. This is the card F8 said M4 actually needed.

## The six formerly-orphaned blocks (driver question 2)

| block | source | home | right? | receiving card fits? |
|---|---|---|---|---|
| TestModuleStem | test_context.py:1541-1560 | 023 | yes — `_module_stem` is in 023's scope | 368, headroom 132 |
| TestClipHit | :2273-2301 | 024 | yes — `_clip_hit` :1440 is in 024's scope | 334, headroom 166 |
| TestDiffFenceWrapping + 4 fixtures | test_prompting.py:196-305 | 014 | yes — its own card, as F4 required | 226, headroom 274 |
| `unclosed_fence` | test_context.py:23-49 | 031 | correct owner, wrong moment (advisory) | 250, headroom 250 |
| `make_archive` | :50-58 | 033 | yes — sole consumer is TestExtractCheckout :187, also 033's | **492, headroom 8** |
| `make_tree` | :16-22 | 048 | last consumer, not first (advisory) | 272, headroom 228 |

Run 3's warning is honoured: CARD-033 (492) and CARD-035/049 (472) received nothing further, and the
two blocks that would have tipped them went to cards with headroom. CARD-033 is now the tightest card
on the board and must not receive another line.

## Size

Method (`_method.md` appendix): a block lifted out of a large file counts twice — deleted from the
source, added to the destination, no rename detection. A whole file that moves counts ~20-40. A test
*conversion* counts twice for the same reason plus rewriting. Ranges are real, from `review.py`
(2,577 lines), `tests/test_context.py` (2,304), `tests/test_prompting.py` (573), `tests/test_diff.py`
(240), `tests/test_requirements.py` (226). `size_exclude` removes only `tests/goldens/**`; no card's
scope touches `*.lock`, `vendor/**`, `node_modules/**` or `docs/cards/**`.

| card | estimated_lines | mine | working |
|---|---|---|---|
| 001 | 60 | 60 | new `ci.yml` ~50 + README note |
| 002 | 340 | 340 | `GITHUB_API`/`OPENROUTER_API` :56-57 + 7 call sites ~17; stub server + canned corpus ~200; offline end-to-end test ~120 |
| 003 | 165 | 165 | Dockerfile 30, .dockerignore 10, two requirements files 13, ci.yml +50, smoke script 60 |
| 004 | 70 | 70 | `release.yml` |
| 005 | 1650 | 1350-1700 | 5 fixture diffs + synthetic tree ~900; harness 250; regenerate CLI 80; test 120. **Waived — driver override, `right_sized: true`.** Fourth costing within 3% |
| 006 | 300 | 300 | DEFAULTS :76-94 (19)x2 + resolution 40; log :98-110 (13)x2; ports stub 15; AST boundary test 150 |
| 007 | 242 | 242 | `parse_target` :650-658 (9)x2 + raise rework 20 + caller catch 10; schemas :559-620 (62)x2=124; tests 40 |
| 008 | 332 | 332 | `_strip_prefix`/`_hunks` :1254-1326 (73) + `diff_paths`/`diff_anchors`/`anchor_violations` :1747-1820 (74) + `diff_size` :687-690 (4) = 151x2=302; test_diff.py rename 30 |
| 009 | 169 | 169 | `MARKER_RE` :64-75 (12)x2; parse/compose 50; delegation 25; new tests 70 |
| 010 | 332 | 334 | `budgets`/`Accounting` :1821-1872 (52) + `_capped`/`_truncation_markers`/`_open_fence` :796-854 (59) + `_truncate_inline` :1551-1566 (16) = 127x2=254; report→data 40; churn 40 |
| 011 | 244 | 244 | test_context.py:61-182 (122)x2 |
| 012 | 306 | 306 | `path_matches`/`is_binary`/`merge_ranges`/`windowed` :855-910 (56)x2=112; tests :683-769 (87)x2=174; churn 20 |
| 013 | 462 | 442 | `seg`/`_blocks` :386-402 (17) + `build_lens_prompt` :2169-2201 (33) + LENS_TAIL/consts ~30 = 80x2=160; shared/tail split 80; TestLensPromptBlocks (82)x2=164; TestSeg (19)x2=38 |
| 014 | 226 | 220 | test_prompting.py:196-305 (110)x2 |
| 015 | 392 | 392 | verdict-prompt + consistency extraction from `adjudicate` :2209-2232 and `run_panel` ~70x2=140; TestAdjudicatePrompt :309-414 (106)x2=212; I4 mutation tests 40 |
| 016 | 410 | 410 | all new: port 30, LocalTree 140, EmptyTree 30, InMemoryTree 60, tests 150 |
| 017 | 304 | 304 | `read_source`/`_whole_file_body`/`_file_body`/`_file_tiers` :911-987 (77)x2=154; port rewrite 60; test updates 90 |
| 018 | 458 | 458 | `pack_changed_files` :1041-1253 less trailer (~180) + `_stretch` :988-1016 (29) = 209x2=418; rewrite 40 |
| 019 | 108 | 108 | `_trailer_groups` :1017-1040 (24) + trailer rendering (~30) = 54x2 |
| 020 | 400 | 400 | TestPackChangedFiles :770-1369 = 600 source x2 = 1200, cut three ways; inclusion/skipping third |
| 021 | 400 | 400 | same, budget/utilisation sweeps third — cut points moved per A6, not the delta's 150/280/170 |
| 022 | 400 | 400 | same, trailer/labelling/file-cap third |
| 023 | 368 | 370 | `CODE_SUFFIXES`/`_suffix`/`_module_stem` :1321-1373 (53) + `changed_symbols` :1374-1409 (36) = 89x2=178; TestChangedSymbols (66)x2=132; TestModuleStem (20)x2=40; churn 20 |
| 024 | 334 | 328 | `walk_source`/`_clip_hit`/`grep_repo` :1410-1478 (69) + `pack_call_sites` :1479-1524 (46) = 115x2=230; port rewrite 40; TestClipHit (29)x2=58 |
| 025 | 210 | 210 | TestGrepRepo :1436-1540 (105)x2 |
| 026 | 334 | 334 | TestPackCallSites + Determinism :1561-1727 (167)x2 |
| 027 | 456 | 456 | `pack_conventions` :1567-1701 (135) + `pack_tree` :1702-1746 (45) + `_fence` :1533-1550 (18) = 198x2=396; rewrite 60 |
| 028 | 330 | 330 | TestPackConventions part A ~165x2 (:1728-2033 = 306 total) |
| 029 | 282 | 282 | TestPackConventions part B ~141x2 |
| 030 | 278 | 188-278 | TestPackTree :2034-2127 (94)x2=188; 278 only if the fence fixtures :2128-2172 stay in its span |
| 031 | 250 | 250-342 | TestFenceBalance :2173-2272 (100)x2=200 + `unclosed_fence` (27)x2=54; +90 if the fence fixtures move here |
| 032 | 297 | 297 | `issue_refs`/`resolve_requirements` :1963-2018 (56)x2=112; IssueSource 25; vlog→notes 40; test_requirements.py rename 30 + fake conversion 90 |
| 033 | 492 | 440-492 | `stream_capped`/`extract_checkout`/`fetch_checkout` :1873-1933 (61)x2=122; ApiTree 100; TarballTree 60; tests :183-252 (70)x2=140; `make_archive` (9)x2=18. **98% of ceiling** |
| 034 | 368 | 338 | `load_dotenv` :116-151 (36) + `Doctrine` :626-644 (19) + `resolve_token` :196-240 (45) + `_b64u`/`_app_jwt` :157-195 (39) = 139x2=278; tests 60 |
| 035 | 472 | 442 | `_http` :246-277 (32) + `GitHub` :278-318 (41) + `whoami` :319-329 (11) + `repo_config` :659-671 (13) + `post_review` :2243-2272 (30) + `describe_key` :367-385 (19) + prior-review fetch (15) = 161x2=322; 422 stub test 60; churn 60 |
| 036 | 401 | 393 | `completion_payload` :403-430 (28) + `strip_fence` :431-451 (21) + `openrouter` :452-554 (103) + `_Heartbeat` :335-366 (32) = 184x2=368; ModelClient 25 |
| 037 | 170 | 150 | test_prompting.py:37-86 (50)x2=100 + conversion/fixtures 50 |
| 038 | 230 | 230 | RecordingModelClient 80; new panel tests 150 |
| 039 | 185 | 185 | delete `_b64u`/`_app_jwt` (39); PyJWT signing 25; key-pair JWT test 80; pins 5 |
| 040 | 300 | 300 | httpx client 60; GitHub method updates 60; stub tests 120; churn 40 |
| 041 | 220 | 220 | transport call :492 + exception :493 = 40; retry-ladder test 80; shape test 60; manual plan 0 |
| 042 | 310 | 310 | read-path rewrite 150; tests 150 |
| 043 | 290 | 290 | `post_review` rewrite 80; 422 fallback 60; tests 150 |
| 044 | 306 | 282 | `select` :691-756 (66) + `prior_rounds` orchestration :672-686 (15) = 81x2=162; rework 40; tests 80 |
| 045 | 380 | 364 | `Context` :1934-1962 (29) + `build_context` :2063-2146 (84) + `_checkout_matches_diff` :2019-2062 (44) = 157x2=314; diagnostics 50 |
| 046 | 294 | 256 | TestBuildContext :263-380 + `_FakeGH` :253-262 (128)x2 |
| 047 | 294 | 352 | TestBuildContext :381-556 (176)x2 |
| 048 | 272 | 266 | TestCheckoutMatchesDiff :557-682 (126)x2=252 + `make_tree` (7)x2=14 |
| 049 | 472 | 472-492 | `run_lens` :2202-2208 + `adjudicate` :2209-2232 + `show_review` :2233-2242 + `dispatch_lenses` :2273-2299 + `run_panel` :2300-2366 = 135 less 015's share, x2 ~ 250-270; TestDispatchLenses (91)x2=182; wiring 40. **~95% of ceiling** |
| 050 | 286 | 270 | `review_pr` :2367-2404 (38) + `review_diff_file` :2410-2441 (32) = 70x2=140; wiring 50; tests 80 |
| 051 | 430 | 430 | `build_parser`/`resolve_post`/`resolve_cache`/`main` :2445-2577 (133)x2=266; tests :416-482 (67)x2=134; shim 10; docs 20 |
| 052 | 195 | 195 | conftest.py 120; runner churn 60; deps + CI 15 |
| 053 | 210 | 210 | head predicate 40; note 20; label logic 30; tests 80; goldens excluded |

**Aggregate ~17,400 (manifest's table sums to 17,486, stated as 17,386) against 26,500.** Median ~300.
Breaches: none unwaived. Tightest: 033 (492), 035 (472), 049 (472), 018 (458), 027 (456). Waived: 005.
**Excluded paths applied:** `tests/goldens/**`, on CARD-005 and CARD-053 only. No other
`size_exclude` pattern matches anything in any card's scope.

## Blocking findings

None.

## Advisory findings

- **A1 — four shared fixture groups are mis-homed or unowned.** `_FakeGH` (test_context.py:253-262)
  is owned by nobody, in the gap between the delta's :183-252 and :263-556; it belongs to CARD-046.
  `DIFF`/`PR` (test_prompting.py:88-106) sit in the row that resolves to CARD-037 (M4) but are used by
  CARD-013, 014 and 015 (M2). The four fence fixtures (test_context.py:2128-2172) sit in CARD-030's
  span but serve only CARD-031. `flat` (test_prompting.py:306-308) sits in CARD-014's span but serves
  only CARD-015. Not blocking: a mis-homed fixture fails loudly on import, where a mis-homed test
  class loses coverage silently, and all three of run 3's test classes are correctly placed.
- **A2 — TestSeg's owner is implicit.** Fixed in substance (CARD-037's title scopes it out, CARD-013's
  462 retains its 38) but stated nowhere; the delta's row still groups it with the openrouter tests.
  State it on CARD-013.
- **A3 — the six new siblings and CARD-037 carry no AC text.** Their scope is unambiguous and their
  parents' ACs partition mechanically, which is why this is not F8 again — but write the partition
  down, particularly "the 10,060-case sweep still passes" onto CARD-011 rather than CARD-010.
- **A4 — CARD-023's title and inherited AC assert port work it does not contain.** `changed_symbols`
  takes a diff, not a `SourceTree`; REQ-004 binds `pack_*` assemblers only. Retitle, and give the
  REQ-004 clause to CARD-024.
- **A5 — CARD-051 needs edges to 046, 047 and 048.** Reducing `review.py` to three lines breaks every
  test still addressing `review.*`; within M6 nothing orders 051 after the three `build_context` test
  conversions. Low risk in practice (they are ready far earlier and lower-numbered), zero cost to fix.
- **A6 — two helpers are owned by their last consumer, not their first.** `unclosed_fence` (owner
  CARD-031, M3) is imported by test_prompting.py:15 and test_requirements.py:11, so CARD-014 (M2),
  026, 030 and 032 all relocate consumers first; `make_tree` (owner CARD-048, M6) is called by
  `make_archive` at :54, owned by CARD-033 (M3). Introduce `tests/helpers.py` at the first need.
- **A7 — the manual-test-plan note contradicts itself and REQ-028.** The manifest names 041 and
  043 as the two exemptions and then says the githubkit confirmation rides on 042. REQ-028 (spec:422-425)
  admits exactly two; CARD-043's 422 fallback is stub-testable. Delete the plan from 043.
- **A8 — the stated aggregate is 100 lines light** (17,386 stated, 17,486 summed), and the
  cross-milestone edge list omits 039→034. Both are documentation, not defects.
- **A9 — CARD-046/047's 294/294 is an even halving, not a measured cut.** The semantic cut at :381
  gives ~256/~352. Both under the ceiling; recorded so the persisted `estimated_lines` is not mistaken
  for a measurement.

## Spec observations (not card findings)

None. All three of run 2's spec defects remain corrected at `a490c1a` and I re-verified the two that
bear on this run: REQ-010 names four sites and flags `die` (spec:254-260), REQ-028 names exactly two
exemptions (spec:422-425). REQ-001's layout (spec:108) puts `changed_symbols` and `pack_call_sites` in
one module, which the 023/024 split reaches in two steps — consistent, not a conflict.

## On the driver override (CARD-005)

Endorsed for the fourth time, unchanged: ~1,350-1,700 against the recorded 1,650, `right_sized: true`
correctly applied, goldens excluded via `tests/goldens/**`. Run 2's stronger justification (the fixture
source tree is shared and `pack_tree` renders the whole tree into every fixture's pack) still holds and
should be the reason recorded on the card. It remains the only card on this board whose estimate is
never re-derived before its code is written.

## Knowledge for `KNOWLEDGE.md`

- A test-ownership walk must cover module-level fixtures and helpers between the class boundaries, not
  just the classes. In `tests/test_context.py` and `tests/test_prompting.py` four fixture groups sit
  inside a neighbour's cited line range while being consumed only by a different card (`DIFF`/`PR` at
  `test_prompting.py:88-106` serve three M2 cards from inside the M4 openrouter row; the four fence
  fixtures at `test_context.py:2128-2172` serve TestFenceBalance from inside the TestPackTree row), and
  `_FakeGH` at `test_context.py:253-262` sits in a gap between two cited ranges. Grep each fixture name
  before trusting a line range to imply ownership.
- Splitting a monolith extraction into a code card plus a test-conversion card is only green because
  `review.py` keeps re-exporting the moved names. The corollary: the card that reduces `review.py` to a
  three-line shim must depend on every test-relocation card, not just on the last extraction card —
  otherwise it can be scheduled while tests still reference `review.*` and its suite is red for reasons
  outside its own scope.
- Assign a shared test helper to the card that FIRST needs it in its new home, not the last card that
  uses it. `unclosed_fence` (`test_context.py:23-49`) is imported by `test_prompting.py` and
  `test_requirements.py` and used by four pack test groups, so owning it on the fence-balance card (M3)
  leaves four earlier cards importing it out of a module the target layout deletes.
