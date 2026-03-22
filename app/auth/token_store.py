import time
from typing import Optional


# In-memory blacklist for invalidated JWTs.
# Key: raw token, Value: unix expiry timestamp.
_BLACKLISTED_TOKENS: dict[str, int] = {}


def _prune_expired_tokens() -> None:
    now = int(time.time())
    expired = [token for token, exp_ts in _BLACKLISTED_TOKENS.items() if exp_ts <= now]
    for token in expired:
        _BLACKLISTED_TOKENS.pop(token, None)


def blacklist_token(token: str, exp_unix: Optional[int]) -> None:
    """Store token in blacklist until token expiry."""
    if not token or exp_unix is None:
        return

    _prune_expired_tokens()
    _BLACKLISTED_TOKENS[token] = int(exp_unix)


def is_token_blacklisted(token: str) -> bool:
    """Return True if token was invalidated before expiry."""
    if not token:
        return False

    _prune_expired_tokens()
    return token in _BLACKLISTED_TOKENS
