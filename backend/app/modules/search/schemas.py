import uuid
from typing import Annotated

from pydantic import BaseModel, StringConstraints


class SearchRequest(BaseModel):
    # In the body, never the URL: search terms must not reach logs, history or referrers.
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class SearchHit(BaseModel):
    file_id: uuid.UUID
    file_name: str
    chunk_id: uuid.UUID
    page: int | None
    snippet: str
    score: float
