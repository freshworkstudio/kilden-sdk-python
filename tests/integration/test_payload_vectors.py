"""The payload vector runner (SPEC §9): replay every call from
vectors/payload.json through a real client against the live mock server and
compare what the mock captured."""

import re

import pytest

from kilden import Client

UUID_V7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
ISO_MS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

pytestmark = pytest.mark.integration


def apply_call(client: Client, call: dict) -> None:
    args = call["args"]
    opts = args.get("opts", {})
    if call["method"] == "track":
        client.track(
            args["distinct_id"],
            args["event"],
            args.get("properties"),
            timestamp=opts.get("timestamp"),
            uuid=opts.get("uuid"),
        )
    elif call["method"] == "identify":
        client.identify(
            args["distinct_id"],
            args.get("traits"),
            timestamp=opts.get("timestamp"),
            uuid=opts.get("uuid"),
        )
    elif call["method"] == "alias":
        client.alias(args["previous_id"], args["distinct_id"])
    else:
        pytest.fail(f"unknown method {call['method']}")


def check_field(name: str, got, want) -> None:
    if want == "<uuid_v7>":
        assert UUID_V7.match(got), f"{name}: {got!r} is not a v7 uuid"
    elif want == "<iso8601_utc_ms>":
        assert ISO_MS.match(got), f"{name}: {got!r} is not wire-form"
    else:
        assert got == want, f"{name}: {got!r} != {want!r}"


def test_payload_vectors(vectors, mock):
    doc = vectors("payload.json")
    failures = []
    for v in doc["vectors"]:
        mock.control("/__mock/reset", {})
        client = Client(
            "sk_test_secret", host=mock.base, flush_at=1000, flush_interval=60
        )
        apply_call(client, v["call"])
        client.flush()
        client.close()
        events = mock.captured()["events"]
        try:
            if v.get("expect") == "discarded":
                assert events == [], f"expected discard, captured {events}"
            else:
                assert len(events) == 1, f"expected 1 event, captured {len(events)}"
                e = events[0]
                want = v["expect_event"]
                check_field("event", e["event"], want["event"])
                check_field("distinct_id", e["distinct_id"], want["distinct_id"])
                check_field("uuid", e["uuid"], want["uuid"])
                check_field("timestamp", e["timestamp"], want["timestamp"])
                assert e["properties"] == want["properties"], (
                    f"properties: {e['properties']} != {want['properties']}"
                )
        except AssertionError as err:
            failures.append(f"{v['name']}: {err}")
    assert not failures, "\n".join(failures)
