"""Identity-token signing (SPEC §6): HS256 by hand over the byte-frozen
canonical JSON form, so the same inputs produce the same token in every
Kilden SDK. Deliberately not attached to the event client — signing a token
should not require an event queue."""

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any, Optional

_MAX_TTL = 604_800  # 7 days; identity tokens are short-lived by design


def _canonical_json(value: Any) -> str:
    # Keys sorted at every level, compact separators, UTF-8 preserved, and
    # &, <, > plus the JS line separators U+2028/U+2029 escaped the way Go's
    # encoding/json does (SPEC §6.1).
    out = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return (
        out.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class IdentitySigner:
    """Signs short-lived identity tokens for Kilden's trust model.

    Only ever sign a ``sub`` your backend authenticated. Signing a
    client-supplied id lets anyone impersonate anyone — with a "verified"
    stamp on top.
    """

    def __init__(self, identity_secret: str, *, kid: str) -> None:
        if not isinstance(identity_secret, str) or identity_secret == "":
            raise ValueError("identity_secret must be a non-empty string")
        if not isinstance(kid, str) or kid == "":
            raise ValueError("kid is required: the platform looks the secret up by kid")
        self._secret = identity_secret.encode("utf-8")
        self._kid = kid

    def sign(
        self,
        sub: str,
        *,
        ttl: int = 3600,
        traits: Optional[Mapping[str, Any]] = None,
        _iat: Optional[int] = None,
    ) -> str:
        if not isinstance(sub, str) or sub == "":
            raise ValueError("sub must be the non-empty distinct_id your backend authenticated")
        if not isinstance(ttl, int) or isinstance(ttl, bool) or not 0 < ttl <= _MAX_TTL:
            raise ValueError(f"ttl must be in (0, {_MAX_TTL}] seconds")

        iat = int(time.time()) if _iat is None else _iat
        payload: dict[str, Any] = {"sub": sub, "iat": iat, "exp": iat + ttl}
        if traits:
            payload["traits"] = dict(traits)

        header = {"alg": "HS256", "kid": self._kid, "typ": "JWT"}
        header_b64 = _b64url(_canonical_json(header).encode("utf-8"))
        payload_b64 = _b64url(_canonical_json(payload).encode("utf-8"))
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        signature = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        return f"{header_b64}.{payload_b64}.{_b64url(signature)}"
