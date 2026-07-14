import json
import threading
import time

import pytest

from kilden import Client
from kilden.transport import TransportResponse


class FakeTransport:
    """Scriptable transport: a list of responses, then 200s forever."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.lock = threading.Lock()

    def send(self, url, body, headers):
        with self.lock:
            self.requests.append((url, body, headers))
            if self.responses:
                return self.responses.pop(0)
        return TransportResponse(status=200, body=b'{"status":"ok"}')

    def bodies(self, path="/capture"):
        with self.lock:
            out = []
            for url, body, headers in self.requests:
                if not url.endswith(path):
                    continue
                if headers.get("Content-Encoding") == "gzip":
                    import gzip

                    body = gzip.decompress(body)
                out.append(json.loads(body))
            return out


def client(transport=None, **kw):
    kw.setdefault("flush_at", 1000)
    kw.setdefault("flush_interval", 60)
    c = Client(
        "sk_test_secret", host="http://mock.invalid", transport=transport or FakeTransport(), **kw
    )
    c._jitter = lambda: 1.0
    c._sleep = lambda s: None
    return c


def events_sent(t: FakeTransport):
    return [e for b in t.bodies() for e in b["batch"]]


def test_constructor_rejects_bad_keys():
    with pytest.raises(ValueError):
        Client("")
    with pytest.raises(ValueError, match="secret"):
        Client("wk_public_key_123")


def test_track_and_flush_delivers():
    t = FakeTransport()
    c = client(t)
    c.track("user_1", "signup", {"plan": "pro"})
    c.flush()
    sent = events_sent(t)
    assert len(sent) == 1
    e = sent[0]
    assert e["event"] == "signup"
    assert e["distinct_id"] == "user_1"
    assert e["properties"] == {"plan": "pro"}
    assert len(e["uuid"]) == 36
    c.close()


def test_invalid_input_drops_never_raises():
    t = FakeTransport()
    c = client(t)
    c.track("", "e")
    c.track("u", "")
    c.track(None, "e")  # type: ignore[arg-type]
    c.track("u", 42)  # type: ignore[arg-type]
    c.track("u" * 513, "e")
    c.track("u", "e" * 201)
    c.track("u", "ok", {"f": object()})  # unserializable properties
    c.track("u", "ok", timestamp="not a time")
    c.flush()
    assert events_sent(t) == []
    c.close()


def test_identify_and_alias_wire_shapes():
    t = FakeTransport()
    c = client(t)
    c.identify("user_1", {"plan": "pro"})
    c.identify("user_2")
    c.alias("anon_x", "user_3")
    c.flush()
    sent = events_sent(t)
    assert sent[0]["event"] == "$identify"
    assert sent[0]["properties"] == {"$set": {"plan": "pro"}}
    assert sent[1]["properties"] == {"$set": {}}
    assert sent[2]["event"] == "$alias"
    assert sent[2]["distinct_id"] == "anon_x"
    assert sent[2]["properties"] == {"$alias": "user_3"}
    c.close()


def test_explicit_uuid_and_timestamp():
    t = FakeTransport()
    c = client(t)
    c.track(
        "u", "e", uuid="0197fa10-7a2b-7c3d-8e4f-5a6b7c8d9e0f", timestamp="2026-01-02T03:04:05.678Z"
    )
    c.flush()
    e = events_sent(t)[0]
    assert e["uuid"] == "0197fa10-7a2b-7c3d-8e4f-5a6b7c8d9e0f"
    assert e["timestamp"] == "2026-01-02T03:04:05.678Z"
    c.close()


def test_queue_cap_drops_new_event():
    t = FakeTransport()
    c = client(t, max_queue_size=3)
    for i in range(5):
        c.track("u", f"e{i}")
    assert c.dropped_count == 2
    c.flush()
    assert [e["event"] for e in events_sent(t)] == ["e0", "e1", "e2"]
    c.close()


def test_batches_chunk_at_1000():
    t = FakeTransport()
    c = client(t, max_queue_size=3000)
    for _ in range(1500):
        c.track("u", "e")
    c.flush()
    sizes = [len(b["batch"]) for b in t.bodies()]
    assert sum(sizes) == 1500
    assert max(sizes) <= 1000
    c.close()


def test_gzip_over_threshold():
    t = FakeTransport()
    c = client(t)
    c.track("u", "small")
    c.flush()
    c.track("u", "big", {"pad": "x" * 5000})
    c.flush()
    small = t.requests[0]
    big = t.requests[1]
    assert "Content-Encoding" not in small[2]
    assert big[2]["Content-Encoding"] == "gzip"
    c.close()


def test_retry_on_5xx_then_success():
    t = FakeTransport(TransportResponse(status=500), TransportResponse(status=503))
    c = client(t)
    sleeps = []
    c._sleep = sleeps.append
    c.track("u", "e")
    c.flush()
    assert len(t.requests) == 3  # two failures, then success
    assert sleeps == [0.5, 1.0]
    assert c.dropped_count == 0
    c.close()


def test_retry_respects_retry_after():
    t = FakeTransport(TransportResponse(status=429, headers={"retry-after": "7"}))
    c = client(t)
    sleeps = []
    c._sleep = sleeps.append
    c.track("u", "e")
    c.flush()
    assert sleeps == [7.0]
    assert len(t.requests) == 2
    assert c.dropped_count == 0
    c.close()


def test_no_retry_on_401():
    t = FakeTransport(TransportResponse(status=401, body=b"unknown write_key"))
    c = client(t)
    c.track("u", "e")
    c.flush()
    assert len(t.requests) == 1
    assert c.dropped_count == 1
    c.close()


def test_retries_exhausted_drops_and_counts():
    t = FakeTransport(*[TransportResponse(status=0, error="boom")] * 4)
    c = client(t)
    c.track("u", "e")
    c.flush()
    assert len(t.requests) == 4  # 1 + 3 retries
    assert c.dropped_count == 1
    c.close()


def test_corrupt_200_body_retries():
    t = FakeTransport(TransportResponse(status=200, body=b"{garbage"))
    c = client(t)
    c.track("u", "e")
    c.flush()
    assert len(t.requests) == 2
    assert c.dropped_count == 0
    c.close()


def test_close_is_idempotent_and_drops_after():
    t = FakeTransport()
    c = client(t)
    c.track("u", "before")
    c.close()
    c.close()
    c.track("u", "after")
    assert [e["event"] for e in events_sent(t)] == ["before"]
    assert c.dropped_count == 1


def test_disabled_client_is_a_noop():
    t = FakeTransport()
    c = Client("sk_x", enabled=False, transport=t)
    c.track("u", "e")
    c.identify("u")
    c.flush()
    c.close()
    assert t.requests == []
    assert c.get_feature_flag("f", "u", default="fallback") == "fallback"


def test_flush_interval_flushes_without_flush_call():
    t = FakeTransport()
    c = Client("sk_x", host="http://mock.invalid", transport=t, flush_at=1000, flush_interval=0.05)
    c.track("u", "timed")
    time.sleep(0.4)
    assert [e["event"] for e in events_sent(t)] == ["timed"]
    c.close()


def test_flush_at_triggers_early_flush():
    t = FakeTransport()
    c = Client("sk_x", host="http://mock.invalid", transport=t, flush_at=2, flush_interval=60)
    c.track("u", "a")
    c.track("u", "b")
    deadline = time.monotonic() + 2
    while not events_sent(t) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(events_sent(t)) == 2
    c.close()


# -- flags ----------------------------------------------------------------


def decide_response(flags):
    return TransportResponse(status=200, body=json.dumps({"flags": flags}).encode())


def test_flag_value_and_is_enabled():
    t = FakeTransport(decide_response({"on": True, "off": False, "exp": "variant_b"}))
    c = client(t)
    assert c.get_feature_flag("on", "u") is True
    assert c.get_feature_flag("off", "u") is False
    assert c.get_feature_flag("exp", "u") == "variant_b"
    assert c.get_feature_flag("missing", "u", default="dflt") == "dflt"
    assert c.is_enabled("on", "u") is True
    assert c.is_enabled("exp", "u") is True
    assert c.is_enabled("off", "u") is False
    # One request total: the rest hit the cache.
    assert len(t.requests) == 1
    c.close()


def test_flag_cache_bypass_with_person_properties():
    t = FakeTransport(
        decide_response({"f": True}),
        decide_response({"f": False}),
        decide_response({"f": True}),
    )
    c = client(t)
    assert c.get_feature_flag("f", "u") is True
    assert c.get_feature_flag("f", "u", person_properties={"plan": "pro"}) is False
    body = json.loads(t.requests[-1][1])
    assert body["person_properties"] == {"plan": "pro"}
    # The bypass did not poison the cache.
    assert c.get_feature_flag("f", "u") is True
    assert len(t.requests) == 2
    c.close()


def test_flag_failure_returns_default_and_does_not_cache():
    t = FakeTransport(TransportResponse(status=0, error="down"), decide_response({"f": True}))
    c = client(t)
    assert c.get_feature_flag("f", "u", default="fallback") == "fallback"
    assert c.get_feature_flag("f", "u") is True  # second call retried the server
    c.close()


def test_flag_empty_args_return_default():
    t = FakeTransport()
    c = client(t)
    assert c.get_feature_flag("", "u", default=True) is True
    assert c.get_feature_flag("f", "", default=True) is True
    assert t.requests == []
    c.close()
