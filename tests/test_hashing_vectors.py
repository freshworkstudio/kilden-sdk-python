"""Frozen rollout-hashing vectors (SPEC §8.3, §9). v1 never evaluates flags
locally; the function is pinned now so local evaluation cannot diverge later."""

from kilden import _hashing


def test_rollout_vectors(vectors):
    doc = vectors("flag-hashing.json")
    assert len(doc["rollout"]) >= 200
    for v in doc["rollout"]:
        assert int(_hashing.bucket(v["flag_key"], v["distinct_id"])) == v["bucket_floor"], v


def test_variant_vectors(vectors):
    doc = vectors("flag-hashing.json")
    for v in doc["variants"]:
        variants = [(x["key"], x["rollout_percentage"]) for x in v["variants"]]
        assert _hashing.variant_for(v["flag_key"], v["distinct_id"], variants) == v["expected"], v
