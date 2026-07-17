"""Supabase S3-compatible storage for user avatars.

All S3 credentials are read from ``app.config.settings`` (loaded from .env by
pydantic-settings), never from ``os.environ`` directly. The client is built
lazily and reused so we don't pay connection setup on every request.
"""

from __future__ import annotations

import threading
from typing import Optional

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings


# Maps stored object extension <-> content type for the objects we serve back.
EXTENSION_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}

_client = None
_client_lock = threading.Lock()


class AvatarStorageError(RuntimeError):
    """Raised when the avatar object store is unavailable or a call fails."""


def is_enabled() -> bool:
    return settings.s3_enabled


def _get_client():
    """Return a cached boto3 S3 client pointed at the Supabase S3 endpoint."""
    global _client
    if not settings.s3_enabled:
        raise AvatarStorageError("S3 storage is not configured")
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = boto3.client(
                    "s3",
                    endpoint_url=settings.S3_ENDPOINT,
                    aws_access_key_id=settings.S3_ACCESS_KEY,
                    aws_secret_access_key=settings.S3_SECRET_KEY,
                    region_name=settings.S3_REGION,
                    config=BotoConfig(
                        signature_version="s3v4",
                        s3={"addressing_style": "path"},
                        # Supabase's S3 gateway occasionally resets connections.
                        # A small retry count absorbs a single transient blip, but
                        # we keep attempts + timeouts low so that when storage is
                        # genuinely unreachable we fail FAST instead of hanging the
                        # request (avatar checks sit on the login/profile path).
                        retries={"max_attempts": 2, "mode": "standard"},
                        connect_timeout=3,
                        read_timeout=5,
                    ),
                )
    return _client


def _avatar_key(user_id: str, extension: str) -> str:
    return f"{user_id}/avatar.{extension}"


def upload_avatar(user_id: str, extension: str, data: bytes, content_type: str) -> str:
    """Upload avatar bytes, removing any prior avatar for this user first.

    Returns the object key that was written.
    """
    client = _get_client()
    _delete_existing(client, user_id)
    key = _avatar_key(user_id, extension)
    try:
        client.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    except ClientError as exc:  # pragma: no cover - network failure path
        raise AvatarStorageError(f"Failed to upload avatar: {exc}") from exc
    return key


def _delete_existing(client, user_id: str) -> None:
    for ext in EXTENSION_CONTENT_TYPES:
        try:
            client.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=_avatar_key(user_id, ext))
        except ClientError:
            continue


def delete_avatar(user_id: str) -> None:
    client = _get_client()
    _delete_existing(client, user_id)


def find_avatar(user_id: str) -> Optional[tuple[str, str]]:
    """Return ``(extension, content_type)`` for a stored avatar, or None.

    Uses ``head_object`` so we don't download the body just to check existence.
    A ``ClientError`` means "no such object" for that extension (try the next);
    a ``BotoCoreError`` (e.g. connection reset) is a real failure and is raised.
    """
    client = _get_client()
    for ext, content_type in EXTENSION_CONTENT_TYPES.items():
        try:
            client.head_object(Bucket=settings.S3_BUCKET_NAME, Key=_avatar_key(user_id, ext))
            return ext, content_type
        except ClientError:
            continue
        except BotoCoreError as exc:  # pragma: no cover - network failure path
            raise AvatarStorageError(f"Failed to look up avatar: {exc}") from exc
    return None


def fetch_avatar(user_id: str) -> Optional[tuple[bytes, str]]:
    """Download avatar bytes for a user. Returns ``(data, content_type)`` or None."""
    client = _get_client()
    for ext, content_type in EXTENSION_CONTENT_TYPES.items():
        try:
            response = client.get_object(Bucket=settings.S3_BUCKET_NAME, Key=_avatar_key(user_id, ext))
        except ClientError:
            continue
        except BotoCoreError as exc:  # pragma: no cover - network failure path
            raise AvatarStorageError(f"Failed to fetch avatar: {exc}") from exc
        return response["Body"].read(), content_type
    return None


def fetch_avatar_ext(user_id: str, extension: str) -> Optional[tuple[bytes, str]]:
    """Download avatar bytes for a specific, known extension.

    Preferred over ``fetch_avatar`` when the extension is already known (e.g.
    from the proxy URL), because it issues a single S3 GET instead of probing
    every extension in turn.
    """
    content_type = EXTENSION_CONTENT_TYPES.get(extension)
    if not content_type:
        return None
    client = _get_client()
    try:
        response = client.get_object(Bucket=settings.S3_BUCKET_NAME, Key=_avatar_key(user_id, extension))
    except ClientError:
        return None
    except BotoCoreError as exc:  # pragma: no cover - network failure path
        raise AvatarStorageError(f"Failed to fetch avatar: {exc}") from exc
    return response["Body"].read(), content_type
