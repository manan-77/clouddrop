# 0014 - Semantic search is one permission-filtered SQL query

## Context

Search must return only what the caller may read (root `CLAUDE.md`: filter in the same SQL query), keep search terms out of URLs and logs, and stay correct when the caller can see only a tiny slice of a large index.

## Decision

- `POST /api/v1/search` with the query in the body (it creates nothing, so 200). Page and page size stay in the URL as for every list.
- The query embeds the text with `embed_query`, then ranks chunk vectors by cosine distance. The access rule from `docs/permissions.md` is part of the same statement: owner of the workspace, or a grant on the file, or a grant on a folder above it, never below a deleted folder; only `ready`, undeleted files, and only the latest version. Folder access is computed by walking down from the user's granted folders (one small set) instead of walking up from every file.
- **Approximate index under-fetch.** The HNSW index returns only its nearest few candidates and the filter runs afterwards, so a user who can see a small slice gets nothing (measured: 0 of 10 with 20 visible vectors among 20,000). The query enables pgvector 0.8 iterative scans (`hnsw.iterative_scan = strict_order`) for its transaction; on an older server it falls back to a wider candidate list (`hnsw.ef_search = 1000`).
- A minimum similarity (`SEARCH_MIN_SCORE`, default 0.6) drops weak matches. BGE scores are compressed: measured with the real model on three short documents, related questions scored 0.73 to 0.82 and unrelated ones 0.44 to 0.51, so 0.6 sits in the gap. It still has to be re-measured on real, longer documents.
- The best `SEARCH_POOL_SIZE` (100) chunks are grouped to the best chunk per file and paged in memory. `total` is the number of files in that pool, not an exhaustive count.
- Rate limited per user. If the embedder cannot run the answer is 503 `search_unavailable`; the query is never logged.

## Consequences

- A very selective filter on a huge index can scan up to the iterative-scan cap before it gives up; results then may be fewer than requested, never wrong.
- No exhaustive result count and no deep paging: search shows the best results.
- Switching the embedding model changes scores, so the threshold must be re-tuned (see ADR 0013).
