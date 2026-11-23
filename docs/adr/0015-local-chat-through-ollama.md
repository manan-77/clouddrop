# 0015 - Chat answers come from a local Ollama model behind one interface

## Context

Question answering (RAG) and summaries need a chat model. The Azure gateway is not available, the project runs on one laptop (16 GB), and document text must not leave the machine (root `CLAUDE.md`, security baseline). ADR 0013 made the same choice for embeddings.

## Decision

- **Ollama on the same machine, model `qwen3:4b-instruct`** (about 2.5 GB). Tried first: plain `qwen3:4b` is a thinking model; on this Ollama version `think: false` leaked its reasoning into the answer and a trivial question took 20 to 27 s. The instruct variant answered in 2 to 4 s and cited every source in a two-fact test. The model name is a setting (`CHAT_MODEL`), not code.
- **One interface**, `ChatClient.stream(messages) -> ChatStream` (`app/ai/chat.py`). A stream is iterated for text, exposes counts-only `usage` when it finishes, and has an explicit `close()` that cancels the request (a bare generator that never started never cleans up). Azure can replace it later by settings, without touching callers. Only streaming exists: the answer endpoint streams, and a non-streaming call is a join of the stream when summaries need it.
- **The window is `CHAT_NUM_CTX` (8192) and the answer is capped at `CHAT_MAX_OUTPUT_TOKENS` (1024)**, so the prompt budget is the difference. Settings that leave under 2048 tokens for the prompt are refused at startup.
- **The prompt size is checked before sending, with a guaranteed upper bound, not an estimate.** Measured on this model: characters per token is about 5 for English prose, about 1.2 for ids, hashes and random text, and about 1.0 for Hindi. The tokenizer is byte-level, so tokens never exceed UTF-8 bytes; the bound is bytes plus a margin per message. English is counted about 5 times too high, which means fewer retrieved chunks fit, never an overflow. A prompt over the budget raises `PromptTooLargeError`; the answer endpoint trims what it sends so this stays a backstop. Ollama 0.40 also rejects an oversized request with a 400 (it does not truncate); that is mapped to the same error. Older versions may truncate silently, which is why our own check comes first.
- **Failures become one safe error** (`ChatUnavailableError`, 503 `chat_unavailable`) with no provider text. Only a refused connection, 429 and 5xx are retried, a bounded number of times with growing waits that honour `Retry-After` (capped), and only before any text has been produced. A timeout while waiting for the model is not retried: the first request after a quiet period waits while the model loads, and retrying would just wait again (`CHAT_READ_TIMEOUT_SECONDS` is 120).
- **Prompts, answers and server error text are never logged or put in an exception.** Only token counts are logged. A prompt larger than its budget at the end of a stream logs a warning with counts.
- Tests never use the real server: an autouse fake replaces `get_chat_client`. The client itself is tested against a fake Ollama (split lines, mid-stream failure, wrong shapes, closing early). A real-model check is opt-in (`RUN_LOCAL_MODEL_TESTS=1`) and includes the proof that the byte bound is never below the real token count.

## Consequences

- A 4B model is weaker than a hosted one and follows instructions and citations less reliably; the answer endpoint must verify citations and treat output as untrusted text.
- Because English is counted high, about 5 chunks of 1,000 characters fit with room for the question; larger contexts need exact counts (the final line of a stream reports the real prompt size, which can be used to tune this).
- `think` is not sent. Using a thinking model later means handling its reasoning text separately.
- The server must be reachable and the model pulled; when it is not, chat is unavailable (503) while search keeps working.
