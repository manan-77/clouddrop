import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


class AnswerRequest(BaseModel):
    # In the body, never the URL: questions are the user's words about their files.
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    # Ask about one file only. It must still be readable by the caller: this narrows, never widens.
    file_id: uuid.UUID | None = None


class Citation(BaseModel):
    label: str  # the [s1] style label the answer text uses
    file_id: uuid.UUID
    file_name: str
    chunk_id: uuid.UUID
    page: int | None


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    text: str


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    # Only sources that were really retrieved. A label in the text that is not listed here is not a
    # source and must not be shown as one.
    citations: list[Citation]
    # The model stopped at the output limit instead of finishing.
    cut_off: bool = False


class ErrorEvent(BaseModel):
    # The answer failed after it had started (the HTTP status was already 200). No details.
    type: Literal["error"] = "error"
    code: str


AnswerEvent = Annotated[TokenEvent | DoneEvent | ErrorEvent, Field(discriminator="type")]
