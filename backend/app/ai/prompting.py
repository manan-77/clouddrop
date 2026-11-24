"""What every prompt that contains file text has in common."""

import re

_FENCE = re.compile(r"<<<|>>>")
_FENCE_SAFE = {"<<<": "‹‹‹", ">>>": "›››"}


def fence_safe(text: str) -> str:
    """File text must not be able to write the fence that closes its own block."""
    return _FENCE.sub(lambda match: _FENCE_SAFE[match.group()], text)
