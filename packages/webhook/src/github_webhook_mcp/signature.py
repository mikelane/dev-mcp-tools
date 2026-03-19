"""HMAC-SHA256 signature verification for GitHub webhook payloads."""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify a GitHub webhook HMAC-SHA256 signature.

    Args:
        payload: The raw request body bytes that were signed.
        signature: The ``sha256=<hex>`` signature string from the
            ``X-Hub-Signature-256`` header.
        secret: The shared webhook secret configured in GitHub.

    Returns:
        ``True`` if the signature is valid, ``False`` otherwise.
    """
    if not signature.startswith("sha256="):
        return False
    expected = (
        "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(expected, signature)
