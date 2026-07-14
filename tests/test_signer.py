import pytest

from kilden import IdentitySigner


def test_kid_is_required():
    with pytest.raises(TypeError):
        IdentitySigner("secret")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        IdentitySigner("secret", kid="")


def test_empty_secret_rejected():
    with pytest.raises(ValueError):
        IdentitySigner("", kid="k1")


def test_ttl_bounds():
    signer = IdentitySigner("secret", kid="k1")
    with pytest.raises(ValueError):
        signer.sign("user_1", ttl=0)
    with pytest.raises(ValueError):
        signer.sign("user_1", ttl=-5)
    with pytest.raises(ValueError):
        signer.sign("user_1", ttl=604_801)
    assert signer.sign("user_1", ttl=604_800).count(".") == 2


def test_empty_sub_rejected():
    signer = IdentitySigner("secret", kid="k1")
    with pytest.raises(ValueError):
        signer.sign("")


def test_token_shape_and_determinism():
    signer = IdentitySigner("secret", kid="k1")
    a = signer.sign("user_1", _iat=1_730_000_000)
    b = signer.sign("user_1", _iat=1_730_000_000)
    assert a == b
    assert a.count(".") == 2
    assert "=" not in a  # base64url without padding


def test_secret_never_in_errors():
    signer = IdentitySigner("super-secret-value", kid="k1")
    try:
        signer.sign("", ttl=0)
    except ValueError as e:
        assert "super-secret-value" not in str(e)
