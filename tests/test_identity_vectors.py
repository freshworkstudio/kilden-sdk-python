"""Byte-exact identity-token vectors from kilden-sdk-spec (SPEC §6.1, §9)."""

from kilden import IdentitySigner


def test_identity_vectors_byte_exact(vectors):
    doc = vectors("identity.json")
    assert len(doc["vectors"]) >= 10
    for v in doc["vectors"]:
        signer = IdentitySigner(v["secret"], kid=v["kid"])
        token = signer.sign(
            v["sub"],
            ttl=v["exp"] - v["iat"],
            traits=v.get("traits"),
            _iat=v["iat"],
        )
        assert token == v["token"], f"vector {v['name']} diverges"
