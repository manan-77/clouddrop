# 0013 - Local embeddings with a fixed 384-dimension vector

## Context

Semantic search needs every chunk turned into a vector. The AI gateway (Azure APIM) is not available yet, the project is run on one laptop, and document text must not leave the machine unless the owner decides otherwise (root `CLAUDE.md`, security baseline). The vector size becomes a database column, so it is the one choice that is expensive to change.

## Decision

- **Model: `BAAI/bge-small-en-v1.5`, 384 dimensions, 512-token input**, run in-process through **fastembed** (ONNX, no PyTorch). Chunks are about 1,000 characters (about 250 tokens), well inside the input limit.
- The model name and size are defined **once** (`app/ai/embeddings.py`: `EMBEDDING_MODEL`, `EMBEDDING_DIM`). The migration writes 384 out (migrations never import app code). Every `chunk_embeddings` row stores its `model` and `dim`, so a model change is detectable.
- **Queries and documents are embedded differently on purpose** (`embed_query` vs `embed_documents`): BGE is trained with a search instruction on the query side only.
- The index is **HNSW with cosine distance**. A chunk has at most one vector (unique `chunk_id`); deleting a chunk deletes its vector.
- The pipeline gets an `embed` stage after `extract`. **A file becomes `ready` only after its last stage has succeeded**, which is also what lets non-owners see and download shared files.
- The embedder is a small interface (`Embedder`) so tests use a fake and the Azure gateway can replace it later by settings, without touching callers.

## Consequences

- Moving to another model (for example an Azure embedding model) means a new column or table with its own size, a re-embed of every chunk, and a new migration. This is documented, not automatic.
- English-oriented quality; the model is about 70 MB, downloaded once into `EMBEDDING_CACHE_DIR`. Set that directory somewhere that survives restarts (a container volume in production) and **pre-populate it** where the container cannot reach the internet: if the model cannot be loaded, files end as `failed` with `embedding_unavailable` once the retries run out.
- fastembed adds about 150 MB to the backend environment (onnxruntime, tokenizers, numpy); `pgvector` adds the SQLAlchemy vector type.
- Embedding runs on the CPU in the worker. Throughput is modest and bounded by `EMBEDDING_BATCH_SIZE`; a very large document takes minutes, which the stage's stale-job and retry rules already cover.
- The database role that runs migrations must be allowed to `CREATE EXTENSION vector`, or the extension must be created once by an administrator (CI and local setup do this).
