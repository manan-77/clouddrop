# 0017 - The answer stream is read through the HTTP client, not fetch

## Context

`POST /api/v1/answers` streams server-sent events (ADR 0016). `EventSource` cannot send a body or a header, so the browser needs either `fetch` with a stream reader or the HTTP client reading progressive text. `fetch` is promise-only (the frontend rules forbid promises for observable work), bypasses the sign-in interceptor (no bearer token, no single refresh on 401, no CSRF header), and would need its own cancellation and error mapping.

## Decision

- `AnswersApi.ask()` uses Angular's `HttpClient` with `responseType: 'text'` and `reportProgress: true`. On the default XHR backend each progress event carries the text received so far (`partialText`), so the client keeps one position and parses the complete events after it. The app does not enable the fetch backend (it cannot report upload progress either, lesson 48), so this holds.
- **One HTTP path.** Sign-in, the single token refresh, error handling and cancellation are the interceptor's and the client's, exactly as for every other call. Unsubscribing aborts the request, which closes the model request on the server.
- Every event is validated field by field before it is used. A stream that ends without `done` or `error`, or that contains anything else, is a failure (never a short answer). A refused request answers in JSON but is read as text, so its body is parsed back before the error resolver sees it.
- The page ends an answer on `done`, `error`, a failure or Stop, and ignores a new question while one is running. The answer is interpolated text; only the sources in the final `done` event are listed.

## Consequences

- If the fetch backend is ever enabled, `partialText` is not provided and this client must change; the specs build their progress events by hand, so they would not notice. The ADR and the comment in `AnswersApi` are the reminder.
- A response buffered by a proxy shows up only at the end. The API sends `X-Accel-Buffering: no` and the web proxy has `proxy_buffering off`; this still has to be seen working in a real browser through the dev proxy.
- Whole answers are held in memory as one string (a few kilobytes: the output is capped).
