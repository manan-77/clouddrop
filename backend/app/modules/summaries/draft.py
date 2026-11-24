"""What the model said, checked. Nothing it returns is trusted to have the right shape."""

import json
import re
from dataclasses import dataclass

from app.modules.summaries.constants import CATEGORIES, OTHER_CATEGORY

MAX_SUMMARY_CHARS = 1200
MAX_TAGS = 5
MAX_TAG_CHARS = 30

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_SPACES = re.compile(r"\s+")
# A tag is a plain word or two: no markup, quotes or symbols from file text reach the stored data.
_TAG = re.compile(r"[\w][\w .+'-]*")


@dataclass(frozen=True)
class SummaryDraft:
    summary: str
    category: str
    tags: list[str]


def shorten(text: str, limit: int) -> str:
    "At most `limit` characters, cut at a word and marked."
    text = _SPACES.sub(" ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" .,;:-") + "…"


def _category(value: object) -> str:
    if isinstance(value, str):
        wanted = value.strip().casefold()
        for category in CATEGORIES:
            if category.casefold() == wanted:
                return category
    return OTHER_CATEGORY


def _tags(value: object) -> list[str]:
    items = value.split(",") if isinstance(value, str) else value
    if not isinstance(items, list | tuple):
        return []
    tags: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        tag = _SPACES.sub(" ", item).strip().strip("#").casefold()
        if tag and len(tag) <= MAX_TAG_CHARS and _TAG.fullmatch(tag) and tag not in tags:
            tags.append(tag)
    return tags[:MAX_TAGS]


# A string value (with escapes) after a key, for a reply whose JSON as a whole is broken.
def _string_after(key: str) -> re.Pattern[str]:
    return re.compile(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"')


_SUMMARY_VALUE = _string_after("summary")
_CATEGORY_VALUE = _string_after("category")


def _salvage(text: str) -> dict[str, object] | None:
    """A small model sometimes writes a good summary and category and then loses its place (it
    repeats itself inside `tags`). The summary is the part that matters, so keep what can be read
    cleanly; the tags are left out. A summary that was cut off before its closing quote is not
    salvaged: half a sentence is worse than none."""
    found: dict[str, object] = {}
    for key, pattern in (("summary", _SUMMARY_VALUE), ("category", _CATEGORY_VALUE)):
        match = pattern.search(text)
        if match:
            try:
                found[key] = json.loads(f'"{match.group(1)}"')
            except ValueError:
                return None
    return found if "summary" in found else None


def parse_draft(raw: str) -> SummaryDraft | None:
    """The summary, category and tags in the model's reply, or None if there is no usable summary.

    A category outside the list becomes "Other" and bad tags are dropped: those are small and
    harmless. A missing or empty summary is not, so the whole reply is refused.
    """
    text = _FENCE.sub("", raw.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1:
        return None
    data: object
    try:
        if end <= start:
            raise ValueError("no closing brace")
        data = json.loads(text[start : end + 1])
    except ValueError:
        data = _salvage(text[start:])
    if not isinstance(data, dict):
        return None
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    return SummaryDraft(
        summary=shorten(summary, MAX_SUMMARY_CHARS),
        category=_category(data.get("category")),
        tags=_tags(data.get("tags")),
    )
