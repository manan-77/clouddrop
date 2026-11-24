# 0018 - Chunks follow paragraphs and sentences

## Context

The real run (ADR 0013 to 0016, `tasks/todo.md` 2.3) showed the first chunker was too crude. It cut fixed windows of 1000 characters at the nearest space, so chunks started mid-sentence (". Prices are fixed"), ended mid-word, and mixed several topics. A chunk that mixes four sections gives a blurred vector: the best chunk for "when do I pay the bill" was the second one, not the one holding the payment clause.

## Decision

- **Text is cut at its own boundaries**, in this order: paragraphs (blank lines), then sentences (a `.`, `!` or `?` followed by a capital letter, digit or quote, so "3.5" and "e.g. a" do not end a sentence), then words, then a hard cut for text with no spaces. A piece is never cut while it fits.
- **Pieces are packed into chunks** of at most `CHUNK_SIZE_CHARS` while they fit. The next chunk starts with the **whole trailing sentences** of the previous one, up to `CHUNK_OVERLAP_CHARS`, so it never begins mid-sentence and an answer that straddles a boundary is still in one chunk. Text with no structure at all (no paragraphs or sentences) keeps the old window cut and its character overlap.
- **Chunking is still a pure function of the text and the settings**: the same input gives the same chunks, indexes and hashes, so a rerun rewrites the same rows.
- **The size default is 400 characters with 80 overlap** (it was 1000 and 150). Measured with the real embedding model on a 1.5 KB agreement and a 10-section handbook, 14 questions with a known answer:

| chunker | chunks | top-1 right | top-3 right | chunks starting or ending mid-sentence |
|---|---|---|---|---|
| old, 1000/150 | 5 | 10/14 | 14/14 | 3 starts, 2 ends |
| old, 500/100 | 9 | 13/14 | 14/14 | 7 starts, 5 ends |
| new, 1000/150 | 5 | 11/14 | 14/14 | 0 |
| new, 500/100 | 10 | 12/14 | 14/14 | 0 |
| **new, 400/80** | 12 | 13/14 | 14/14 | 0 |
| new, 300/60 | 19 | 14/14 | 14/14 | 0 |

  300 ranks one more question first but gives thin chunks (about 180 characters) to the answer step, which reads the best few; 400 keeps about a section per chunk. On the real agreement the scores of the best chunk rose from 0.62 to 0.72 ("when do I pay the bill"), 0.65 to 0.75 ("late fee") and 0.60 to 0.71 ("who do I call about a delivery"), and unrelated questions stayed at or below 0.49, so the similarity default (0.55) still separates them.
- **Existing files keep their old chunks until they are processed again.** `python -m app.worker.reprocess` queues every ready, undeleted file for the extract and embed stages again (the scan is not repeated); a file is not `ready`, and so is missing from search, for the seconds it takes.

## Consequences

- More chunks per document (about twice as many for prose), so a little more embedding time and storage.
- It is not perfect: "how long is the contract" still ranked the termination clause above the term clause on the real agreement. A different embedding model, a relative cutoff or neighbouring-chunk context would be the next steps; none is built.
- Changing the size or the splitter again means running the reprocess command again.
- The sentence rule is for Latin text with capitals; text in other scripts falls back to words and windows, which is the old behaviour.
