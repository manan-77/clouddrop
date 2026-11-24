# 0019 - Summaries and categories are written in the background

## Context

A file should come with a short summary, a category and a few tags. The model is small and local (ADR 0015), it can be slow or down, its output is not always valid, and the text it reads is untrusted file content.

## Decision

- **A separate job, never part of the pipeline.** A file becomes `ready` without waiting for the model. When the pipeline finishes, the worker asks for a summary (`file_summaries`, one row per file version, state `pending`, `ready` or `failed`) and queues `summaries.generate_summary`. A failing or absent model never touches the file.
- **Only for new content, or on request.** The row is keyed by file version: processing the same version again (a redelivery, the reprocess command) finds the row and does nothing. A new version is new content and gets its own. `POST /files/{id}/summary` asks for a new one on purpose; asking while one is waiting changes nothing. The model name and the prompt version are stored with every summary, so an old result is recognisable after a better prompt.
- **A sweeper like the pipeline's.** Every five minutes it asks for the summary of ready files that never had a request and sends again requests nobody picked up (a lost message or a crash), marking what it sent so the next pass takes others.
- **The model answers in JSON** (Ollama's JSON mode, `json_output` on the chat client) and the reply is checked: the summary must be non-empty text and is cut at a word at 1200 characters; the category must be one of a fixed list (`Contract`, `Invoice`, `Report`, ... `Other`; anything else becomes `Other`); tags are at most five plain lowercase words of at most 30 characters (markup, symbols and long phrases are dropped). A small model sometimes writes a good summary and then loses its place inside `tags` and repeats itself until the limit; the summary and category are then **salvaged** from the broken reply and the tags left out, because a summary is worth keeping. A summary cut off before its closing quote is not kept.
- **Every call is short.** Each call is capped at `SUMMARY_MAX_OUTPUT_TOKENS` (300), a per-call cap on the chat client that can lower but never raise the configured limit. Without it a runaway reply took about 80 seconds.
- **Long documents are read in parts**, each summarised on its own (parts are at most `SUMMARY_PART_BYTES`, counted in bytes like every prompt), and the part summaries are then described together. At most `SUMMARY_MAX_PARTS` parts and `SUMMARY_TIME_BUDGET_SECONDS` seconds are used, after which the result covers what was read and is marked `partial`. The global task time limit is not raised.
- **Untrusted text.** File text is fenced and labelled untrusted in the user message only; the rules are in the system message (the fence helper is shared with the answer prompts, `app/ai/prompting.py`).
- **Failures are recorded as short codes** (`no_text`, `bad_output`, `prompt_too_large`, `chat_unavailable`, `too_many_attempts`), never exception text. The model being briefly down is retried with growing pauses, up to `SUMMARY_MAX_ATTEMPTS`.
- **Access goes through the one door.** `GET /api/v1/files/{id}/summary` needs read access to the file, `POST` needs write access (an editor or the owner); both use `FileService.get_file`, so an unreadable file is exactly as missing as any other. `POST` is rate limited per user and answers 202 with the pending summary.

## Consequences

- A summary is not instant: about ten seconds per document on the local model, longer for long documents. The screen has to show a pending state.
- A very long document is summarised from its first parts only (`partial`).
- The categories are a product decision in code (`constants.py`); adding one means a release.
- A summary can be wrong or miss the point; it is a convenience, not a record. It is shown as text and never as HTML.
- Summary tasks share the default queue with the pipeline, and one can run for minutes; a long run can delay a file that is waiting to be processed. A separate queue and worker for summaries is the next step if that is noticed.
- If the model or the prompt changes, old summaries stay as they were until someone asks again; `prompt_version` says which they are.
