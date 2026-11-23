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


class SearchService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.repo = SearchRepository(session)
        self.settings = settings

    def search(
        self, user_id: uuid.UUID, query: str, params: PageParams
    ) -> tuple[list[SearchHit], int]:
        """The best chunk of each matching file, best first, paged over the top of the pool.

        `total` counts the files found among the best `search_pool_size` chunks, not every file
        that could ever match: a search shows the best results, not an exhaustive list.
        """
        try:
            vector = embeddings_module.get_embedder().embed_query(query)
        except Exception as exc:  # the model could not load or run; never log the query text
            logger.warning("Search embedding failed: %s", type(exc).__name__)
            raise ServiceUnavailableError(
                "Search is unavailable right now", code="search_unavailable"
            ) from exc
        matches = self.repo.closest_chunks(
            user_id, vector, self.settings.search_min_score, self.settings.search_pool_size
        )
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
            snippet=match.content[: self.settings.search_snippet_chars],
            score=round(match.score, 4),
        )
