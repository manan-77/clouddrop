# CLAUDE.md — CloudDrop AI frontend

> These instructions OVERRIDE default behavior. When a rule here conflicts with a habit, the rule wins. The root `CLAUDE.md` also applies; cross-boundary contracts (error shape, auth, file status, upload protocol) live there and are mirrored, not redefined, here.

## Boundary

Angular SPA for the CloudDrop API: auth, file explorer, upload, sharing, AI search and chat. It **renders and dispatches intent**. The server owns every access decision, status transition and quota; the UI reflects what the server returned.

It never talks to AWS or the AI gateway except the one S3 upload step (presigned, direct). It never holds a secret.

## Stack & commands

Angular (latest stable; **pin the exact version when scaffolding and record it**) · TypeScript `strict` · RxJS · Signals · Vitest · ESLint · Prettier. Styling: SCSS with design tokens as CSS custom properties. **No UI kit, Tailwind or icon font without an ADR.**

```bash
npm start                  # ng serve with proxy.conf.json -> backend
ng build | ng test | ng lint
npm run format             # prettier
```

Dev uses a proxy so the app is same-origin with the API (cookies and CORS behave like production). **No hostname, port or API base is baked into the build**; the API base is the relative path `/api/v1`.

## Structure & layering

```
src/app/
  core/       auth/ (session, interceptors, guards), api/ (typed clients), error/ (resolver, handler), config/
  shared/     ui/ (presentational components), pipes/, directives/
  features/<name>/   pages/ (containers), components/ (presentational), state/ (signal stores)
```

**`features -> shared, core`; features never import each other; `shared` never imports `features`.** Import via path aliases, no `../../..` chains. Public surface of a folder is its `index.ts`.

- **Components render and dispatch.** No `HttpClient`, no URLs, no business rules in components.
- **Services/stores orchestrate** state with signals. **API clients own transport only** — one typed client per resource under `core/api`, generics on every call.
- A child component used twice moves to `shared/ui`. Components stay under ~200 lines, templates under ~150.

## Modern Angular only

| Don't | Do |
|---|---|
| `@NgModule` | standalone components + lazy route arrays |
| `*ngIf` / `*ngFor` / `ngSwitch` | `@if` / `@for` (with `track`) / `@switch` |
| constructor DI | `inject()` |
| `@Input()` / `@Output()` | `input()` / `output()` |
| `@ViewChild` | `viewChild()` |
| class guards / interceptors | functional `CanActivateFn` / `HttpInterceptorFn` |
| `BehaviorSubject` for UI state | `signal()` / `computed()` |
| `.subscribe()` in a component | `toSignal()`, `async` pipe, or `takeUntilDestroyed()` |
| `[ngClass]` / `[ngStyle]` objects | `[class.x]` / `[style.--x]` |
| `any` | `unknown` + narrowing |
| template-driven forms | typed reactive forms |
| `console.log` | the error handler / telemetry sink |

## Components, state & RxJS

- Every component: `standalone: true` + `ChangeDetectionStrategy.OnPush`. **Container** (routing/data) -> **presentational** children (`input()`/`output()` only, no injected services).
- **Never call a method in a template binding** — it reruns every change-detection cycle. Use `computed()` or a pipe.
- `computed()` is created once (a field), never inside a method/getter. Subscribe to the narrowest slice; pass stable inputs (no fresh object/array literals or arrow functions in bindings). `track` by a real id.
- **No `async`/`await`, `firstValueFrom`, `lastValueFrom`, `toPromise` on observables.** A promise cannot be cancelled, debounced, retried or torn down with the component. Stay in RxJS and end in `toSignal()` / `async` pipe / `takeUntilDestroyed()`. Promise-only platform APIs (`File.arrayBuffer`, `navigator.*`, dynamic `import()`) are wrapped at the boundary with `from()`/`defer()`.
- **No nested `subscribe()`.** Flatten with the right operator: `switchMap` (latest wins — search, navigation), `concatMap` (ordered writes), `mergeMap` (independent, with a concurrency cap — uploads), `exhaustMap` (ignore while in flight — submit buttons). Side effects in `tap`, not `map`. `shareReplay({ bufferSize: 1, refCount: true })`, never bare `shareReplay(1)`. `catchError` returns a typed fallback or rethrows.
- Debounce and cancel user-driven requests (search-as-you-type = `debounceTime` + `distinctUntilChanged` + `switchMap`). **Retry only idempotent reads**, bounded backoff — **never auto-retry a write.**

## Forms & validation

Typed reactive forms only. **Every rule the server enforces is also declared on the control**, shown **inline next to the field** (never only a toast), and blocks submit while invalid. This is UX only — the server remains the authority. Mirror: name length/characters, max upload size, allowed types, email format, password rules.

## Loading & in-flight feedback

Every API call must show something is happening — an idle-looking screen gets clicked twice.

- **Reads:** a skeleton/spinner over the content area; never a bare empty panel.
- **Writes:** progress **on the control that started it**, disable it, label in the present participle ("Saving…"). **Guard the handler too** (`exhaustMap` or an in-flight flag, reset in `finalize`) — `disabled` does not stop Enter or a fast double-click.
- **Loading, empty and error are three explicit states**, and a failed request returns the UI to an interactive state with a retry.

## Auth & session

- Access token lives **in memory** (a signal in the auth service). **Never** `localStorage`/`sessionStorage`/cookies you can read from JS, never in a URL, never logged.
- The refresh token is an `HttpOnly` cookie the JS cannot see. On `401` the interceptor does a **single-flight** refresh (concurrent 401s wait on one refresh), retries the original request once, and on failure clears the session and routes to login. **No per-call 401 logic anywhere else.**
- The auth interceptor attaches `Authorization` **only to same-origin API requests**. **It must never add the header to the S3 upload URL** — S3 rejects the extra header and it would leak the token to a third party.
- Route guards redirect; they are UX, not security.

## Errors

- One **error resolver** maps the API error envelope (`error.code`) to a user-safe message (with a generic fallback). Never render `err.error.message`, a status code, or a stack trace raw.
- A global `ErrorHandler` is mandatory; risky lazy routes get their own fallback. Never write an empty `error:` handler or a bare `catch {}`.
- Do not log to `console` in shipped code; use the handler/telemetry sink, never including file names or document text.

## Uploads (the hard part)

Follow the protocol in the root file exactly.

- Request upload instructions from the API, then `PUT`/`POST` **directly to S3** with `HttpClient` (`reportProgress: true, observe: 'events'`) and **no Authorization header**. Then call `complete`.
- **Never read a whole file into memory.** Use `File.slice()` for multipart parts; upload parts with `mergeMap(…, 3)` (small concurrency cap); retry a failed *part* (idempotent) with backoff, not the whole file.
- Multipart needs the part's `ETag` response header — it requires S3 CORS `ExposeHeaders: ETag`; if it is missing, fail loudly with a clear developer error.
- Upload queue is a signal-based store: per-file status, progress, cancel (unsubscribe + tell the server to abort), and removal on completion. Cancelling must stop network work.
- Client-side size/type checks are UX only; the server re-validates.
- After `complete`, **poll** status with `timer` + `switchMap`, stop on a terminal state (`ready`, `failed`, `infected`, `needs_ocr`), use backoff, and tear down with `takeUntilDestroyed()`.
- Downloads: request a presigned URL on click and navigate/anchor to it (`rel="noopener noreferrer"`). Do not pull large files into a blob in memory, and never store or log the URL.

## AI chat & search

- Search is debounced and cancels in-flight requests. **Search terms, file names and document text never go into URLs or query params** (history, referrer and server logs leak them); keep them in component/store state. Routes use opaque ids.
- Chat responses stream; model the stream as an observable (SSE/fetch stream wrapped with `defer`), append tokens through a signal, and cancel on destroy or "Stop".
- **AI output is untrusted text.** Render with interpolation (`white-space: pre-wrap`). **Never `[innerHTML]`, `bypassSecurityTrust*`, `eval`, `new Function` or `document.write`.** Markdown rendering is allowed only through one shared sanitizing component chosen by ADR.
- Citations link to `/files/:id` using the ids the server returned; never construct a link from model-generated text.
- Show explicit states: "searching…", "no results", "AI unavailable — try again".

## Security

- Never trust the client: hiding a button is not authorization; permissions displayed come from the server response.
- **No raw HTML injection** (above). **No secrets in the bundle** — everything shipped is public. **No external scripts or stylesheets**; self-host fonts and icons. External links use `rel="noopener noreferrer"`.
- Treat shared-file metadata (names, descriptions) as untrusted strings; always interpolate.
- Do not put PII, file names or document text in `localStorage`, URLs, logs or analytics.

## Styling

Component-scoped SCSS and design tokens (CSS custom properties) — **never inline styles, never hardcoded colours/spacing/font sizes**; add a missing token instead. Use `[class.x]` for conditionals. **Light and dark must both work** (check every new screen). Theme state is written in one place only. Don't pierce encapsulation with `::ng-deep`. Respect `prefers-reduced-motion`.

## Accessibility

Icon-only controls need `aria-label`; use semantic elements instead of rebuilding buttons from `div`s; keep focus-visible styles and keyboard operability (the file explorer must be fully keyboard-navigable); modals trap and restore focus; announce upload/processing status changes via `aria-live`.

## Routes

Lists are plural kebab-case; one record nests under its list: `/files` · `/files/:id` · `/folders/:id`; static segments (`new`) precede `:id`; no verb before the id; no `-view`/`-detail` route names. **Every route is lazy** (`loadComponent`/`loadChildren`). Build URLs with relative navigation or a path helper, never string literals scattered in templates. Guard per route that needs it.

## Strings, dates, sizes

One display date format app-wide through a single pipe (assumed `DD/MM/YYYY HH:mm`, 24-hour — confirm); wire is ISO-8601 UTC and is converted only at the display boundary; **never compute on display strings**. File sizes go through one `fileSize` pipe. Status labels map from the `FileStatus` union in one place. The app is English-only.

## Dependencies & bundle

Add a package only under the root dependency bar. Heavy/optional UI (markdown, charts, PDF preview) is code-split by dynamic `import()` at the point of use, never on the boot path. Import narrowly, never `import * as`. Budgets are guardrails: a warning is a bug, and raising one needs a reason. Check the chunk report after any bundling change.

## TypeScript, naming & comments

`strict` on; **no `any`**, no `!` on genuinely nullable values, no lying casts (`as unknown as`). Explicit return types on exported functions; `import type` for types. Mirror backend wire types in `core/api/models`, with discriminated unions for status/role. Files `kebab-case` by role (`file-list.page.ts`); classes `PascalCase`; selectors prefixed `cd-`; observables end in `$`; signals are noun phrases; services verb-first (`getFiles`) — never `handle`/`process`/`data`; no `I` prefix. **Comment the *why* only**; never restate the code.

## Testing

Vitest; name tests `method_scenario_expected`. Test what users rely on: the auth interceptor (attach, skip S3, single-flight refresh), error resolver mapping, guards, the upload state machine (progress, cancel, part retry, failure leaves UI interactive), status polling stop conditions, permission-driven UI, and that AI output renders as text. Every new service/guard/interceptor ships with specs. Never delete a test file without approval.

## PR gate (frontend)

- [ ] Standalone + OnPush; no method calls in bindings; `track` on every `@for`
- [ ] No `await`/`firstValueFrom`; no nested or leaked `subscribe()`
- [ ] Every API call has loading/empty/error states; writes disabled + guarded against double fire
- [ ] Auth header never sent to S3; token only in memory
- [ ] No `[innerHTML]`/`bypassSecurityTrust*`; AI output rendered as text
- [ ] No file names, search terms or document text in URLs, storage, logs
- [ ] No inline styles or hardcoded design values; light and dark verified
- [ ] Server validation rules mirrored inline on the field
- [ ] Routes lazy; no new external script/stylesheet; budgets not raised
- [ ] `ng build`, `ng test`, `ng lint`, `npm run format` clean (output reported)
