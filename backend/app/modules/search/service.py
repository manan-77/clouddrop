import logging
import uuid

from sqlalchemy.orm import Session

from app.ai import embeddings as embeddings_module
from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.core.pagination import PageParams
from app.modules.search.repository import ChunkMatch, SearchRepository
from app.modules.search.schemas import SearchHit

logger = logging.getLogger(__name__)


def _snippet(text: str, limit: int) -> str:
    """The start of a chunk as a readable line: not from the middle of a sentence, not cut inside a
    word. Chunks are fixed-size windows, so they can begin after a sentence ended ("`. Prices are`")
    and the limit can fall inside a word."""
    text = text.lstrip(" \t\r\n.,;:)-")
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" .,;:-") + "\u2026"


class SearchService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.repo = SearchRepository(session)
        self.settings = settings

    def matching_chunks(
        self,
        user_id: uuid.UUID,
        query: str,
        limit: int,
        only_file_id: uuid.UUID | None = None,
    ) -> list[ChunkMatch]:
        """The chunks closest in meaning to `query` among files the caller may read, best first.

        The one retrieval path: search lists files from it and answers are built from it, so the
        access rule, the similarity threshold and the embedder's failure handling live here only.
        """
        try:
            embedder = embeddings_module.get_embedder()
            vector = embedder.embed_query(query)
        except Exception as exc:  # the model could not load or run; never log the query text
            logger.warning("Search embedding failed: %s", type(exc).__name__)
            raise ServiceUnavailableError(
                "Search is unavailable right now", code="search_unavailable"
            ) from exc
        return self.repo.closest_chunks(
            user_id, embedder.model, vector, self.settings.search_min_score, limit, only_file_id
        )

    def search(
        self, user_id: uuid.UUID, query: str, params: PageParams
    ) -> tuple[list[SearchHit], int]:
        """The best chunk of each matching file, best first, paged over the top of the pool.

        `total` counts the files found among the best `search_pool_size` chunks, not every file
        that could ever match: a search shows the best results, not an exhaustive list.
        """
        matches = self.matching_chunks(user_id, query, self.settings.search_pool_size)
        best_per_file: dict[uuid.UUID, ChunkMatch] = {}
        for match in matches:  # already best first, so the first chunk seen per file is its best
            best_per_file.setdefault(match.file_id, match)
        ranked = list(best_per_file.values())
        page = ranked[params.offset : params.offset + params.page_size]
        return [self._hit(match) for match in page], len(ranked)

    def _hit(self, match: ChunkMatch) -> SearchHit:
        return SearchHit(
            file_id=match.file_id,
            file_name=match.file_name,
            chunk_id=match.chunk_id,
            page=match.page,
            snippet=_snippet(match.content, self.settings.search_snippet_chars),
            score=round(match.score, 4),
        )
