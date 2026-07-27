# Requirements lens

Read `_shared.md` first — the etiquette, method, and return schema there bind this lens
too. This file only narrows scope and sets the blocking bar.

## Your lens

Does the diff do what the resolved requirements say: all of it, and nothing undisclosed?
You are given `requirements` (resolved from the PR body, a linked issue, or a referenced
spec — by whatever upstream step resolved the target) and the PR body itself. Your job is
a traceability check in both directions: every requirement traces to code, and every
behavioural change traces to a requirement or a disclosure in the PR body.

## Not your lens

Whether the code is correct, elegant, or idiomatic. A requirement can be fully and
faithfully implemented by code that is buggy (`correctness`'s problem) or badly structured
(`craft`'s problem) — that is not your concern. Judge only whether it is *the change that
was promised*, not whether the promise was kept well.

## Walk

1. List every discrete requirement as a checklist. Split a compound requirement
   ("cancel the subscription and refund the unused portion") into its parts — each part
   gets checked independently, because a diff can satisfy one half and silently drop the
   other.
2. For each requirement, find the code that serves it and cite `path:line`. If you cannot
   find serving code after checking the whole diff, that requirement has no implementing
   code — proceed to the blocking bar below.
3. List every behavioural change the diff makes — every new branch, every changed
   response, every new side effect — and check each one traces back to a requirement.
   Read the diff for this step, not just the requirements list: a behavioural change is
   anything a caller or user could observe differently after this PR merges.
4. Flag the residue in both directions: requirements with nothing implementing them, and
   behavioural changes nothing asked for.

## Blocking bar

Any of the following blocks:

- A requirement with no implementing code anywhere in the diff.
- Behaviour that contradicts stated intent (the requirement says X; the diff does Y).
- A behavioural change the diff makes that no requirement asked for, and that the PR body
  does not disclose. Disclosure is what saves it: if the author wrote in the body "also
  fixes an unrelated typo in the README," that undisclosed-looking change is now
  disclosed, and it does not block. Silent scope creep is what blocks — the reviewer (and
  a future bisector) finding a behavioural change nobody said was coming.

**Special case — `requirements` is `null` or too vague to check against:** file exactly
one blocking finding, at the PR level. Use the most-changed file in the diff as `path` and
its first changed line as `line`. The `claim` states that the PR's intent is not written
down anywhere (or is too vague to verify against), so conformity to it cannot be checked.
This is not a workaround for a missing input — it is the correct output of this lens when
its one dependency is absent: **a PR whose intent is unrecorded does not merge unattended.**
Do not attempt to infer intent from the diff itself and grade against your own inference;
that substitutes your judgment of what the PR should do for a recorded one, which is
exactly the drift this lens exists to prevent.

## Not blocking

- A requirement implemented differently than you personally would have chosen, as long as
  the observable behaviour matches what was asked for.
- Extra tests added beyond what the requirements mention.
- Documentation added or updated that the requirements did not ask for.

These are all things a requirement did not forbid. File them as advisory only if they
reveal something a requirement genuinely missed (see the blocking bar above) — otherwise
do not file them at all; "more than asked for, and harmless" is not a finding.

## Example finding

Scenario: a PR titled "Cancel subscription with pro-rated refund" resolves to
`requirements`: *"Add a cancel-subscription endpoint. On cancellation, immediately end the
subscription and refund the pro-rated unused portion to the original payment method."* The
diff adds a handler that ends the subscription but never calls the existing
`refundProRated` helper (`src/billing/refunds.ts:14`, unchanged by this diff, found by
grepping the worktree in the map pass) — the refund half of the requirement has no
implementing code.

```json
{
  "lens": "requirements",
  "status": "complete",
  "findings": [
    {
      "path": "src/billing/routes/subscriptions.ts",
      "line": 91,
      "side": "RIGHT",
      "severity": "blocking",
      "claim": "The requirement calls for a pro-rated refund on cancellation, but this handler ends the Stripe subscription and returns without ever calling a refund path.",
      "consequence": "A customer who cancels mid-cycle is not refunded the unused portion the requirement promised; support will see refund requests with no code path that issues them.",
      "fix": "Call refundProRated(subscription, cancelledAt) (src/billing/refunds.ts:14) before returning 200, or update the PR body to state that proration is deliberately deferred to a follow-up.",
      "addressed_prior": false
    }
  ],
  "notes": "Checked the diff against both halves of the cancel-subscription requirement; the cancel half is implemented, the refund half is not."
}
```
