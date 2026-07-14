"""Kilden server-side SDK.

Implements the Kilden Server SDK Specification
(https://github.com/kildenhq/kilden-sdk-spec): batched event capture,
identity-token signing and remotely evaluated feature flags, with zero
runtime dependencies.
"""

from .client import Client
from .signer import IdentitySigner
from .transport import Transport, TransportResponse
from .version import VERSION

__version__ = VERSION
__all__ = ["Client", "IdentitySigner", "Transport", "TransportResponse", "__version__"]
