from enum import StrEnum


class SummaryStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


# What a file can be called. A fixed list keeps the categories consistent across files (a model
# left free invents a new word each time); anything it names outside the list becomes OTHER.
CATEGORIES: tuple[str, ...] = (
    "Contract",
    "Invoice",
    "Report",
    "Policy",
    "Letter",
    "Meeting notes",
    "Manual",
    "Presentation",
    "Spreadsheet",
    "Resume",
    "Article",
    "Other",
)
OTHER_CATEGORY = "Other"
