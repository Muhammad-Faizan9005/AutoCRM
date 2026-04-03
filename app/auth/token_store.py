import hashlib
import time
from datetime import datetime, timezone
from typing import Optional

from supabase import Client

from app.database import run_db_operation

_REVOCATION_TABLE = "revoked_tokens"

# In-memory fallback for environments where DB table is unavailable.
# Key: sha256(token), Value: unix expiry timestamp.
_BLACKLISTED_TOKENS: dict[str, int] = {}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _prune_expired_tokens() -> None:
    now = int(time.time())
    expired = [token_hash for token_hash, exp_ts in _BLACKLISTED_TOKENS.items() if exp_ts <= now]
    for token_hash in expired:
        _BLACKLISTED_TOKENS.pop(token_hash, None)


def _unix_to_iso(exp_unix: int) -> str:
    return datetime.fromtimestamp(exp_unix, tz=timezone.utc).isoformat()


def _iso_to_unix(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


async def blacklist_token(db: Client, token: str, exp_unix: Optional[int]) -> None:
    """Persist token revocation until token expiry, with in-memory fallback."""
    if not token or exp_unix is None:
        return

    _prune_expired_tokens()
    token_hash = _token_hash(token)
    _BLACKLISTED_TOKENS[token_hash] = int(exp_unix)

    payload = {
        "token_hash": token_hash,
        "expires_at": _unix_to_iso(int(exp_unix)),
    }

    try:
        await run_db_operation(lambda: db.table(_REVOCATION_TABLE).upsert(payload, on_conflict="token_hash").execute())
        await run_db_operation(
            lambda: db.table(_REVOCATION_TABLE)
            .delete()
            .lt("expires_at", datetime.now(timezone.utc).isoformat())
            .execute()
        )
    except Exception:
        # Fallback already stored in memory.
        return


async def is_token_blacklisted(db: Client, token: str) -> bool:
    """Return True if token was invalidated before expiry."""
    if not token:
        return False

    _prune_expired_tokens()
    token_hash = _token_hash(token)

    if token_hash in _BLACKLISTED_TOKENS:
        return True

    try:
        response = await run_db_operation(
            lambda: db.table(_REVOCATION_TABLE)
            .select("token_hash, expires_at")
            .eq("token_hash", token_hash)
            .limit(1)
            .execute()
        )
    except Exception:
        return False

    rows = response.data or []
    if not rows:
        return False

    exp_unix = _iso_to_unix(rows[0].get("expires_at"))
    if exp_unix is not None and exp_unix <= int(time.time()):
        _BLACKLISTED_TOKENS.pop(token_hash, None)
        try:
            await run_db_operation(
                lambda: db.table(_REVOCATION_TABLE).delete().eq("token_hash", token_hash).execute()
            )
        except Exception:
            pass
        return False

    if exp_unix is not None:
        _BLACKLISTED_TOKENS[token_hash] = exp_unix
    return True
