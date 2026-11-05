# Lessons

Rules I derive from review findings so the same mistake is not made twice. Read at session start.

## From PR #1 review (backend auth and storage)

1. **Check-then-act on a parent row needs a lock.** Whenever code checks that a parent (folder) exists and then writes a child, lock the parent row (`FOR SHARE` on writers, `FOR UPDATE` on delete). A soft-deleted parent is not stopped by a foreign key.
2. **Every requirement in the contract is implemented or explicitly deferred in the PR.** Quota and rate limiting were in the standards and missing from the code without a word. Before opening a PR, walk the contract bullets for the area and either build, or write "deferred to <branch>" in the PR body and the todo.
3. **Every route has `response_model` and an explicit `status_code`, including health checks.** Grep for routes without them before the PR.
4. **Never branch on an exact free-text environment string.** Use a Literal type and fail closed: secure cookies and disabled docs unless the environment is explicitly development or test.
5. **Starlette runs the unhandled-exception handler outside user middleware.** Anything the error response needs (request id) must travel in the ASGI scope, not only in a context variable.
6. **Do pure computations (presigning) before committing.** Commit last, so a failure does not leave half-created rows.
7. **A status that implies the object is gone must not be downloadable.** When deleting an object, check every status set that points at it.
8. **Every numeric query parameter needs both a lower and an upper bound.**
9. **Timeouts, retries and pool sizes belong in settings, even for a client factory.**
10. **Run the PR gate checklist from the CLAUDE.md files literally before requesting review.** Tick each item against the code, not from memory.
12. **Add structural guard tests for rules that are easy to forget** (every route declares a status code and response model). The first run of such a test found 11 routes that broke the rule.
13. **A shared test session must behave like production.** The real session closes (rolls back) per request; the test override must roll back too, or uncommitted work leaks between requests and hides bugs.
14. **Library upgrades change introspection.** In this FastAPI version `include_router` wraps routers, so tests that walk `app.routes` must unwrap them.
11. **Concurrency claims need a concurrency test or an explicit note.** The savepoint-per-test setup cannot exercise races; say so in the PR instead of implying coverage.

## From PR #3 review (docs)

15. **Quote exact paths and prefixes in docs.** A global "base path" sentence made two un-prefixed routes read as prefixed. State exceptions next to the rule.
16. **Describe scope by what the code actually does.** A dependency resolved by a whole router affects every route in it; say "every route", not "the routes that need it".
17. **Template placeholders must satisfy the validators.** A copy-pasted `.env` should start the app, or the comment must say what to change.

## From the frontend scaffold

18. **Check the engine range before scaffolding.** The newest Angular CLI refused the local Node. Read `engines` first and record the pin as an ADR.
19. **`ng add` installs the newest package, not the one matching the workspace.** Re-run with the matching major (`angular-eslint@21`).
20. **Node 25 breaks the global `localStorage` in tests.** Tests that touch storage install their own in-memory Storage.
22. **A fragment link breaks under a base href.** `href="#main"` resolves against `<base href="/">`; move focus in a click handler and test it.
23. **Lookups keyed by server strings must use own-property checks.** `table[code]` returns functions for `constructor`; use `Object.hasOwn` or a Map, and validate array/shape of every field from the wire.
24. **Do not mix a persistent live region with conditional rendering.** Keep the region in the DOM and change only its text.
25. **A visible label must be part of the accessible name.** Do not override a button's visible text with a different aria-label.
26. **Prove lint rules fire.** After adding rules, lint a deliberately bad file once, then delete it.
27. **Test harnesses give host elements their own ids**; assert on what your component renders, not on the host.
21. **Run prettier and the linter before the first commit of any new tier**, and give test host components OnPush too, since the lint rule applies to specs.

## From the frontend auth work

28. **Configure TestBed before the first inject.** Helpers that read the injector (to pre-load a session) must run after `configureTestingModule`, so pass a flag into the setup function.
29. **Spec helpers that wrap `dispatchEvent` must return void explicitly**; an arrow returning the boolean fails type checking.
30. **Verify the cookie and proxy path end to end with curl**, not only with unit tests: the unit tests mock HTTP and cannot see a wrong cookie path.

## From the PR 5 review (auth)

31. **Anything async that writes session state needs a generation check.** A refresh or restore that started before a logout or login must drop its result; bump a counter on every session change and compare it when the response arrives.
32. **Only an explicit 401 from the refresh endpoint ends a session.** Network errors and 5xx must leave the user signed in and let the next call retry.
33. **Match endpoint paths with a pattern, not equality**: trailing slashes, query strings and fragments must not turn an auth call into a normal call. Reject dot segments and encoded dots before treating a URL as same-origin API.
34. **When two standards conflict, do not silently pick one**: record the reading as an ADR, comment it in the code, and flag the standard for the owner.
35. **Server field errors must clear when the field is edited**, and a failed submit should focus the first invalid field.

## From the PR 7 review (folder path)

36. **If a cap makes a query safe, enforce the same cap at write time.** Otherwise the read silently truncates and returns a misleading result.
37. **Tick a todo item only when a test covers it.** The soft-deleted ancestor case was ticked without one.
38. **Standards exceptions are an ADR plus a note for the owner**, not a quiet deviation.
