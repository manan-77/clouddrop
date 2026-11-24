from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class FileSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: Literal["pending", "ready", "failed"]
    summary: str | None
    category: str | None
    tags: list[str]
    # Only the start of a very long document was read.
    partial: bool
    model: str | None
    prompt_version: str | None
    # Why it failed, as a short machine code (for example `bad_output`); null otherwise.
    error_code: str | None
    generated_at: datetime | None
