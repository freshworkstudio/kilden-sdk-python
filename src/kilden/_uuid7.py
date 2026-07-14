"""UUID v7 by hand (SPEC contract 6): 48-bit unix milliseconds, version and
variant bits, 74 random bits. Lowercase canonical form."""

import os
import time


def uuid7() -> str:
    raw = bytearray(int(time.time() * 1000).to_bytes(6, "big") + os.urandom(10))
    raw[6] = (raw[6] & 0x0F) | 0x70  # version 7
    raw[8] = (raw[8] & 0x3F) | 0x80  # RFC 4122 variant
    h = raw.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
