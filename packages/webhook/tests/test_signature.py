from __future__ import annotations

import hashlib
import hmac

from github_webhook_mcp.signature import verify_signature

SECRET = "test-webhook-secret"


def _sign(payload: bytes, secret: str) -> str:
    computed_hmac = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={computed_hmac}"


def test_valid_signature_returns_true() -> None:
    payload = b'{"action": "opened"}'
    signature = _sign(payload, SECRET)

    assert verify_signature(payload, signature, SECRET) is True


def test_invalid_signature_returns_false() -> None:
    payload = b'{"action": "opened"}'
    signature = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

    assert verify_signature(payload, signature, SECRET) is False


def test_wrong_secret_returns_false() -> None:
    payload = b'{"action": "opened"}'
    signature = _sign(payload, "wrong-secret")

    assert verify_signature(payload, signature, SECRET) is False


def test_missing_prefix_returns_false() -> None:
    payload = b'{"action": "opened"}'
    bare_hmac = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()

    assert verify_signature(payload, bare_hmac, SECRET) is False


def test_empty_payload_returns_true() -> None:
    payload = b""
    signature = _sign(payload, SECRET)

    assert verify_signature(payload, signature, SECRET) is True
