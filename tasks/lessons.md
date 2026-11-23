# Lessons: the pre-PR checklist

Distilled from 160 review findings (full history: `tasks/archive/lessons-through-pr28.md`, numbers
in brackets point there). Read at session start. Walk this list against the diff **before** opening a
PR; a finding in review means a rule here was skipped or is missing.

## Contract and permissions
1. **Read the server rule before offering an action in the UI.** For every control, write down which
   role may use it (`docs/permissions.md`, the service code) and cover it in a role-by-action spec table. [120, 122, 160]
2. **Every denial looks like a missing resource (404), including names, counts, parent ids and
   unique-name collisions.** Gate metadata like downloads. [122, 124, 125, 146]
3. **Secrets go in bodies or URL fragments, never paths or queries**, and never to logs, storage or
   the router. [145, 153]
4. **A security control that can be switched off is refused outside local environments**; limits are
   scoped to the abuse they stop and applied after the cheap access check. [69, 126, 133]

## Backend data and jobs
5. **Check-then-act needs a lock or one conditional statement** (`UPDATE ... RETURNING`, `FOR SHARE`
   on the parent), plus a note when tests cannot exercise the race. [1, 11, 149, 150]
6. **Anything retried has an attempts cap kept in the database**, a stage-aware sweeper that orders
   by last hand-over, and an explicit error code when retries run out. [59, 62, 63, 64, 76]
7. **Writes that belong together commit together and fail closed** (audit with the action); do
   side effects and presigning before the commit. [6, 128]
8. **A model/CHECK/enum change ships with its migration and a drift test.** [121, 130]
9. **Settings that depend on each other are validated at startup; tests pin every setting they
   assert on.** [68, 94, 104]
10. **Every route declares `response_model` and `status_code`; every list is paginated with bounds;
    every anonymous write has its own throttle.** [3, 8, 148]

## Frontend state and templates
11. **Async state: only the latest request may update the screen.** Follow route inputs as
    observables with `switchMap`, set `loading` inside the projection (not before it), keep the old
    data while reloading, and key any "last known" cache to what it describes. [138, 141, 142, 157, 159]
12. **Every control that starts a request has an in-flight guard, and a modal cannot be dismissed
    while its request runs.** [43, 44]
13. **"Not loaded" reads as "no permission"; a failed load drops the cached answer.** [137, 144]
14. **No method calls or `$any` in templates** (pure pipes, template refs); tokens used in SCSS must
    exist in `_tokens.scss`. [135, 139]
15. **Selects bind `[selected]` on options; a template ref on a component element needs
    `viewChild(ref, { read: ElementRef })`; a form needs a form directive for `(ngSubmit)`.** [40, 156, 158]
16. **Accessibility is part of "done"**: one persistent live region, visible label inside the
    accessible name, focus moves somewhere sensible when the focused control disappears,
    `aria-current` on the current item, no `title` input or native-event output names. [24, 25, 46, 50, 54]

## Tests
17. **Every async/state change gets a spec for the in-between state** (loading, empty, error, busy,
    changed-while-loading, focus), and a negative spec proves the guard fails without the fix. [37, 140, 155, 159]
18. **Specs must be able to fail**: set a token before asserting "no Authorization", assert state
    after `match()`, use `...Once` for throwing mocks, flush every new request in dialog specs,
    run change detection between steps, `await` a tick for `toObservable` effects. [56, 102, 140, 152, 154]
19. **Fixtures are real**: real documents once a parser reads them, in-memory limiter, throwaway
    Redis DB, never a shared store or a destructive command. [57, 78, 89]

## Process
20. **Run the exact CI commands locally** (`scripts/verify.sh`; CI does not run on PRs into `develop`, so this is the only gate before merge), build after any bulk edit, tick a
    todo only when a test covers it, and say plainly what was not run. [26, 37, 47, 103]
21. **Pin third-party actions to a commit SHA and audit tools to a version; keep advisory checks
    out of the required set.** [107, 108]
22. **A rule copied into SQL (access in search/RAG) gets a differential test against the original on random cases** (`tests/test_search_matches_access.py`), proven by breaking the copy once; hand-picked cases missed a deleted ancestor above a grant.
23. **Grep for an existing constant, helper or pattern before adding one; a value used twice has one owner** (page size drifted to 20/50/100 across screens), and prefer a lint rule over a note. See root `CLAUDE.md` > Consistency.
24. **Measure a number you would otherwise guess before building on it** (tokens per character was 5 for English and 1.0 for ids and Hindi, so a fixed ratio would have overflowed); prefer a bound that cannot be wrong over an estimate.
25. **Standards conflicts are an ADR plus a note for the owner, never a quiet deviation.** [34, 38]

## Review stop rule
Review the local diff once before opening the PR (independent reviewer, no cap on findings). In the
PR, run another round only while the last one found a **blocker or major** (wrong behaviour, data
loss, security, access, accessibility, or a missing test for either). Minors and taste go to
`tasks/todo.md` unless they are security or accessibility. Merge when a round has no blocker or major.

## Adding to this file
Add a rule only when no rule above covers it. If a rule can be a lint rule, structural test or shared
helper, build that instead and keep one line here pointing at it.
