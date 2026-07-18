from __future__ import annotations

import logging

from app.config import settings


logger = logging.getLogger(__name__)


# The insecure placeholder shipped as the JWT_SECRET_KEY default. Booting a
# production instance with this value means every token can be forged, so we
# refuse to start in prod when it has not been overridden.
_INSECURE_JWT_PLACEHOLDER = "your-secret-key-change-in-production-min-32-chars"


def verify_startup_config() -> None:
    """Validate configuration up front instead of mid-request.

    Previously these checks fired lazily the first time a feature was used
    (Mailjet creds inside ``email_service``, the JWT secret never checked at
    all). Running them at startup surfaces a misconfiguration immediately.

    Strictness: a problem aborts startup in production (``DEBUG=False``) with
    an error log, but only logs a warning in development so local runs without
    email or a custom secret still work.
    """
    is_dev = settings.DEBUG
    problems: list[str] = []

    # JWT secret — must never be the shipped placeholder in production.
    if settings.JWT_SECRET_KEY == _INSECURE_JWT_PLACEHOLDER:
        problems.append(
            "JWT_SECRET_KEY is still the insecure default placeholder; set a unique secret"
        )

    # Mailjet — email (invites, notifications, password reset) is not feature
    # flagged, so the app is always expected to be able to send. Require the
    # full credential set at startup.
    if not settings.MAILJET_API_KEY or not settings.MAILJET_SECRET_KEY:
        problems.append("MAILJET_API_KEY and MAILJET_SECRET_KEY are required for email delivery")
    if not settings.MAILJET_SENDER_EMAIL:
        problems.append(
            "MAILJET_SENDER_EMAIL is not configured (falls back to a Mailjet API lookup at send time)"
        )

    if not problems:
        return

    detail = "; ".join(problems)
    if is_dev:
        logger.warning("startup_config_incomplete (DEBUG mode, continuing): %s", detail)
        return
    logger.error("startup_config_check_failed: %s", detail)
    raise RuntimeError(f"Startup configuration invalid: {detail}")
