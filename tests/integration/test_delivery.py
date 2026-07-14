"""End-to-end delivery behavior against the live mock server: retries,
Retry-After, gzip, flags."""

import pytest

from kilden import Client

pytestmark = pytest.mark.integration


def make_client(mock, **kw):
    kw.setdefault("flush_at", 1000)
    kw.setdefault("flush_interval", 60)
    c = Client("sk_test_secret", host=mock.base, **kw)
    c._jitter = lambda: 1.0
    c._sleep = lambda s: None
    return c


def test_retry_after_429_delivers(mock):
    mock.control("/__mock/fail", {"times": 2, "status": 429, "retry_after": 0})
    c = make_client(mock)
    c.track("user_retry", "eventually_delivered")
    c.flush()
    events = mock.captured()["events"]
    assert [e["event"] for e in events] == ["eventually_delivered"]
    assert c.dropped_count == 0
    c.close()


def test_500_then_success(mock):
    mock.control("/__mock/fail", {"times": 1, "status": 500})
    c = make_client(mock)
    c.track("u", "after_500")
    c.flush()
    assert len(mock.captured()["events"]) == 1
    c.close()


def test_401_drops_without_retry(mock):
    mock.control("/__mock/keys", {"public": [], "secret": ["sk_other"]})
    c = make_client(mock)
    c.track("u", "rejected")
    c.flush()
    assert mock.captured()["events"] == []
    assert c.dropped_count == 1
    c.close()


def test_corrupt_response_retries_then_delivers(mock):
    mock.control("/__mock/fail", {"times": 1, "mode": "corrupt"})
    c = make_client(mock)
    c.track("u", "survives_corruption")
    c.flush()
    assert len(mock.captured()["events"]) == 1
    c.close()


def test_gzip_bodies_accepted(mock):
    c = make_client(mock)
    c.track("u", "fat_event", {"pad": "x" * 4000})
    c.flush()
    batches = mock.captured()["batches"]
    assert len(batches) == 1
    assert batches[0]["gzip"] is True
    assert batches[0]["headers"]["Content-Encoding"] == "gzip"
    c.close()


def test_user_agent_header(mock):
    c = make_client(mock)
    c.track("u", "e")
    c.flush()
    ua = mock.captured()["batches"][0]["headers"]["User-Agent"]
    assert ua.startswith("kilden-python/")
    c.close()


def test_flags_against_mock(mock):
    mock.control(
        "/__mock/flags",
        {
            "flags": [
                {"key": "on_flag", "active": True, "rollout_percentage": 100},
                {"key": "off_flag", "active": False, "rollout_percentage": 100},
                {
                    "key": "variant_flag_1",
                    "active": True,
                    "rollout_percentage": 100,
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ],
                },
            ]
        },
    )
    c = make_client(mock)
    assert c.is_enabled("on_flag", "user_42") is True
    assert c.is_enabled("off_flag", "user_42") is False
    assert c.get_feature_flag("missing", "user_42", default="dflt") == "dflt"
    variant = c.get_feature_flag("variant_flag_1", "user_42")
    assert variant in ("control", "test")
    c.close()
