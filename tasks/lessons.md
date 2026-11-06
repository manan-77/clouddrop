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

## From the explorer work

39. **Do not make a dependency global when only some routes need it.** Resolving S3 for every file route turned a missing bucket into an outage of list, rename and delete; declare the dependency on the routes that use it.
40. **A `<form>` needs a form directive for `(ngSubmit)` to fire.** With reactive forms only, wrap controls in a form group, or the browser performs a real submit and reloads the page.
41. **Initialise page-scoped stores lazily**, so opening a page does not load once for the default state and again for the real one.

## From the PR 9 review (explorer)

42. **A state setter must be a no-op when the value is unchanged**, and any 'correct the page' logic must only move when the target is actually different, or inconsistent server counts become an endless reload loop.
43. **Make a modal non-dismissible while its request runs** (Escape, Cancel, backdrop) and tie the page state to the dialog's lifetime; reset dialogs and messages when the route changes.
44. **Every button that triggers a request needs its own in-flight guard**, including reads that start side effects such as downloads.
45. **Read route identifiers from the route path, not from input binding**: input binding also binds query strings, so `/?id=x` could open something unintended.
46. **Do not name a component input `title`**: the static attribute also becomes a native tooltip on the host element.
47. **A scripted find-and-replace over templates must be checked for collateral matches** (it renamed another component's `title` input); the compiler caught it, so always build after a bulk edit.

## From the upload work

48. **Angular's fetch backend cannot report upload progress.** Use the default XHR backend whenever upload progress is needed.
49. **Presigned form posts need the file field last**, and the browser must never attach our credentials to the storage origin; test both.
50. **Do not name component outputs after native DOM events** (for example `cancel`): the native event would also trigger the handler. Use specific names such as `cancelUpload`.

## From the PR 10 review (upload)

51. **Every client step that creates server state needs a matching cleanup on failure and cancel.** Otherwise retries leave duplicate pending rows that count against the quota.
52. **A server-supplied URL must be validated before the client uses it**, especially when an interceptor adds credentials by URL pattern: require another origin and http(s).
53. **Count dragenter/dragleave pairs** (they fire for child elements) instead of toggling a flag, or the highlight flickers.
54. **Keep one persistent live region for progress and status summaries**, not one `role=status` per row.
55. **Do not keep `File` handles in visible state**; hold them privately and release them when the upload is done or cancelled.
56. **Tests that use `match()` consume requests**; assert state (statuses, counts) too, or a following `expectNone` proves nothing. Test URLs must be derived from the runtime origin, not hardcoded.

## From the pipeline work

57. **Never run a destructive Redis or database command against a shared instance for convenience** (I tried `flushdb` to get a clean smoke test). Use a dedicated database number and leave shared data alone.
58. **A subquery over the same table as the outer query must use an alias**, or it auto-correlates and loses its FROM clause.
59. **A periodic sweeper must be able to tell finished work from stuck work.** A file resting in a non-terminal status after all stages ran would be re-enqueued forever unless the sweep also checks the stage rows.
60. **Do not set `ready` before the stage that makes it true exists**; leave the file in `processing` and say so.
61. **macOS has no `timeout` command**; wait loops belong in a small script.

## From the PR 11 review (pipeline)

62. **Catch the unknown exception around every stage.** Only handling the two expected error types leaves jobs stuck `running` for a whole stale period; roll back, release the job, and retry with a cap.
63. **Every retry loop needs an attempts cap** (counted in the database, because redelivery and sweeping bypass Celery's own counter), or one poison file retries forever.
64. **A sweeper must order by when work was last handed over**, not by when the file last changed, and record that moment before sending, or it resends the same oldest files and starves the rest.
65. **Publishing from a request thread must fail fast**: set short broker timeouts and a one-retry publish policy, and test with an unreachable broker.
66. **Make conditional reads conditional**: use the stored ETag as `IfMatch` so every read stage sees the object that was verified.
67. **A test for ordering must observe state at the moment of the call** (use a hook), not only count calls.
68. **Encode operational invariants as startup validation**, not just a test of the defaults (visibility timeout versus task limits).

## From the malware scan work

69. **A security control that can be switched off must be refused outside local environments** (validated in settings), and the off state must be loud in the logs.
70. **Test a protocol client against a small fake server that records the bytes**, so framing, terminators and limits are asserted, not assumed.
71. **Decide the oversize behaviour explicitly**: fail with a clear code, never skip silently.
72. **Do not log scanner replies**: they can echo file content or names.
73. **Parse protocol replies strictly and require the terminator**: a reply cut short must never be interpreted (a signature name can end in "OK"), and an unrecognised reply is "unavailable", never "clean".
74. **A fake server must be able to stall, drop and split replies**, otherwise timeout and truncation tests pass for the wrong reason.
75. **A generator that never started never runs its `finally`**; return a small object with an explicit `close()` and call it in a `finally` around the consumer.
76. **Give an exhausted retry its own error code** when the cause matters (`scan_unavailable`), so a file that was never scanned is not reported as a generic failure.
77. **Adding a stage changes every test that asserts the end state or reads the object**; grep the tests for stage names, `stage.run(` and storage patches before running the suite.
78. **Test fixtures that stand in for documents must be real documents** once a parser reads them; build tiny valid ones in `tests/documents.py` instead of faking magic bytes.
79. **NUL bytes are a binary signal at type detection**, so test NUL stripping at the cleaning function and use other control characters in end-to-end tests.
80. **Hide bound SQL parameters on the engine** (`hide_parameters=True`); any bulk insert of document text otherwise lands in error logs.
81. **Never use library helpers that expand input-controlled structure** (python-docx `row.cells` with `gridSpan`); walk the raw elements and count against the cap as you go.
82. **Cap each parsed XML part, not only the archive total**, and apply ratio checks to parsed parts only so media does not cause false rejections.
83. **A broad `except Exception` around a parser must re-raise the task time-limit exception** so a slow valid file is retried, not marked corrupt.
84. **A "rerun" test must call the write twice and compare rows**, include a shrinking rerun and a failing insert; counting rows once proves nothing.
85. **Delete the external object before the row, and stop on the first storage outage**; the row is the only record of what to clean next run.
86. **Count only what can still become real in quota sums**: abandoned pending uploads must stop counting once past their presign window, not wait for the purge.
87. **A batch lock is only as long as the transaction**: committing per item releases the rest, so lock and re-check each item inside the transaction that deletes it.
88. **A rotation-driven table needs a drain that loops (bounded) and an index on the column the purge filters on**, not one fixed batch per interval.
89. **Tests must never share a real counter store**: inject an in-memory limiter by default; test the Redis implementation separately on a throwaway DB with unique keys and no flush.
90. **Hash rate-limit subjects** (IP, email) before they become keys so Redis holds no PII.
91. **A union of two observable types cannot be called with `.subscribe` in a spec**; branch before subscribing.
92. **Key a per-account limit on the account and the client together**, or one stranger can lock the owner out.
93. **A limiter that reads the socket peer needs the proxy configuration written down in the same PR**, or every user shares one budget in production.
94. **When a feature raises a size limit, trace every later stage that has its own cap** (scanner, extraction) and validate the caps against each other at startup.
95. **Let the server list uploaded parts itself instead of trusting a client part list**; it removes ETag capture from the browser and the trust problem together.
96. **A cleanup deadline must fit the slowest legitimate flow**: multipart uploads need their own, longer deadline than single uploads, and the quota cutoff must follow it.
97. **Test the presigned URL with a client built like production** (SigV4); the default test client signs differently and hides what is or is not signed.
98. **Branch on the server's plan, not on a client guess**: the part size and count come from the API response; the client only slices what it is told.
99. **Put shared guards (external-URL check, storage error type) in one small module** before a second caller needs them.
100. **Retry the whole presign-and-send unit, not just the send**, and classify errors: network, 5xx and 429 retry; other 4xx never do.
101. **After an abort is refused because the work finished, fall back to the delete that works in that state**; swallowing the refusal leaves a file the user cancelled.
102. **A spec asserting "no Authorization header" must set a token first**, or it passes whether or not the interceptor leaks.
103. **Run the exact CI commands locally before pushing a workflow**, including the audit export, so the first CI run is a confirmation, not a discovery.
104. **Tests that build Settings must pin every field they assert on**; an environment variable set by CI or a developer's `.env` otherwise changes the result.
105. **CI's npm must match the one that wrote the lock file**: use the Node line that ships the same npm major (Node 24 / npm 11), not an older LTS.
106. **A lock file written on macOS can miss Linux-only optional peers** (`@emnapi/*` for the wasm runtime); pin them as dev dependencies, with the reason in the PR, so `npm ci` works on every platform.
