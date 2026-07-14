"""Pluggable HTTP transport. The default uses urllib from the standard
library; anything with the same `send` shape can replace it (SPEC §2.1).
Transports never raise — errors come back in the response object."""

import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TransportResponse:
    status: int  # 0 = transport-level failure (timeout, DNS, refused…)
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None


class Transport:
    """Default transport on urllib. One instance per client."""

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    def send(self, url: str, body: bytes, headers: dict[str, str]) -> TransportResponse:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return TransportResponse(
                    status=resp.status,
                    body=resp.read(),
                    headers={k.lower(): v for k, v in resp.headers.items()},
                )
        except urllib.error.HTTPError as e:
            return TransportResponse(
                status=e.code,
                body=e.read(),
                headers={k.lower(): v for k, v in e.headers.items()},
            )
        except Exception as e:  # timeout, connection refused, DNS, TLS…
            return TransportResponse(status=0, error=f"{type(e).__name__}: {e}")
