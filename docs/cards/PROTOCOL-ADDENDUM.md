# Protocol Addendum (project-specific)

Project-specific doctrine that layers **on top of** the plugin's `AGENT-PROTOCOL.md`.
Every phase agent reads the plugin protocol first, then this file. Rules here refine
or add to the shared contract for **this repository only** — they never override the
structured-return format or the sole-writer invariant.

`/retro` appends project-specific process lessons here, each prefixed
`[retro-YYYY-MM-DD]`. Universal lessons belong in the plugin instead — `/retro`
flags those as a plugin PR rather than writing them here.

**Size budget:** this file rides every dispatch — keep it under 4 KB; one line per rule.

<!-- No project-specific rules yet. -->

## Check criteria

Project-specific check criteria, layered on top of the plugin's `checks/` doctrine.
Each checker reads its own target's section here in addition to the plugin's.

Criteria here carry a **`LOCAL-`** id prefix so they never collide with a plugin id
and `/retro` can tell which set a verdict came from. Ids are stable and permanent —
never renamed, never reused. `/retro` owns this section; it may add, edit and prune
`LOCAL-` criteria, but never touches the plugin's.

Add a `## Check criteria — <target>` subsection (`target` ∈ `intake` | `slice` |
`design` | `split` | `deliver`) when a lesson earns one. Format matches the plugin file: a
table of `| id | criterion | severity when failed |`.

<!-- No project-specific criteria yet. -->
