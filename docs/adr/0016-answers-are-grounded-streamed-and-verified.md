# 0016 - Answers are grounded, streamed and verified

## Context

Users ask questions about their files. The model is small and local (ADR 0015), file text is untrusted input, and an answer must never reveal a file the caller may not read.

## Decision

- `POST /api/v1/answers` (a noun; it creates nothing and keeps no history, so the answer is 200). The question is in the body, never the URL. It lives in its own module, `app/modules/rag`, because it needs the search module and the chat client; the `ai` package stays free of module imports.
- **One retrieval path.** The answer uses `SearchService.matching_chunks`, the same permission-filtered query that search uses, so there is no second copy of the access rule (and the comparison test in `tests/test_search_matches_access.py` covers both). An optional `file_id` narrows to one file; it is applied on top of the access rule, so an unreadable file looks exactly like a missing one.
- **Nothing relevant means no model call.** The fixed text "I couldn't find that in your files." is streamed as a normal answer with no citations.
- **The prompt keeps rules and data apart.** The system message holds the rules and nothing from any file. Chunks are rendered in a fenced `DOCUMENTS` block labelled untrusted, with labels `s1`, `s2`, ..., never real ids; the question comes after the block. File text cannot write the fence (`<<<` and `>>>` are replaced), so it cannot close its own block. The model has no tools.
- **Citations are verified in code.** The text is scanned for `[s1]`, `[s1][s2]` and `[s1, s2]`; only labels that were offered are returned, mapped to `{label, file_id, file_name, chunk_id, page}`. A made-up label is dropped from the list; text already streamed cannot be recalled, so clients must show only the labels in `citations`.
- **The prompt budget is enforced.** Chunks are added best first while the byte-bound size (ADR 0015) fits the budget; one that does not fit is skipped. If none fits the answer is 422 `question_too_long`, never an overflow.
- **Everything that can fail with a proper HTTP status happens before streaming:** retrieval, prompt building and opening the model request (429, 422, 503). A failure after the first byte is an `error` event. The database connection is released (commit) before streaming, because a stream can last minutes.
- **Cancellation is real.** `Answer.close()` is idempotent and runs when the events finish, when the client disconnects mid-stream, and as a background task when the response never started.
- The response is `text/event-stream`, `Cache-Control: no-store` and `X-Accel-Buffering: no` so a buffering proxy does not hold the stream.
- **Answers in progress are capped per user** (2 by default, per process). The request rate limit counts starts, but an answer holds a server thread for as long as it streams, so without a cap one user could hold dozens open and starve everyone. The slot is freed when the answer finishes, when it is closed, when starting fails, and (as a last resort, through a finalizer) when the object is garbage collected without ever being closed, for example a client that vanished before the response began. Over the cap the answer is 429 with `Retry-After`.
- A "context too large" refusal from the model server, which our own byte bound should make impossible, is mapped to the same 422 `question_too_long`, never a bare 500. A failure while streaming is logged by its code only.
- Rate limited per user (30 per 10 minutes by default). Questions, answers and file text are never logged; the chat client logs token counts only.

## Consequences

- A 4B model can still ignore the rules or mis-cite; verification only guarantees that a listed source was really offered, not that the claim is supported by it.
- English text is counted high by the budget bound, so about 5 chunks fit; more context needs exact token counts.
- No conversation memory: each question stands alone.
- A monthly per-user token budget is not built (counts are logged per request; storing them per user is a later change).
- The stream is consumed with `fetch`, not `EventSource`, because it is a POST.
