"""The frozen rollout hashing (SPEC §8.3). Not part of the public API: v1
evaluates flags remotely. It lives here, tested against the spec vectors,
so local evaluation can arrive later without a divergence risk."""

import hashlib
from typing import Union


def _fraction(data: str) -> float:
    digest = hashlib.sha256(data.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def bucket(flag_key: str, distinct_id: str) -> float:
    return _fraction(f"{flag_key}:{distinct_id}") * 100


def variant_for(
    flag_key: str, distinct_id: str, variants: "list[tuple[str, int]]"
) -> Union[str, bool]:
    point = _fraction(f"{flag_key}:{distinct_id}:variant") * 100
    cumulative = 0.0
    for key, weight in variants:
        cumulative += weight
        if point < cumulative:
            return key
    return True
