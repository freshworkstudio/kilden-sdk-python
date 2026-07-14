"""WSGI app for the fork-safety test (SPEC contract 9).

With ``gunicorn --preload`` this module is imported in the MASTER process:
the client below is constructed pre-fork, its worker thread lives in the
master, and the five parent events sit in the master's queue. Workers fork
afterwards and inherit both. A fork-safe SDK must discard the inherited
queue in each worker (those events belong to the parent) and restart the
worker thread — otherwise the parent events get sent once per worker and
the worker's own events never leave, because the inherited worker thread
does not exist after fork.
"""

import os
import time
from urllib.parse import parse_qs

from kilden import Client

client = Client(
    os.environ.get("KILDEN_TEST_KEY", "sk_test_secret"),
    host=os.environ["KILDEN_TEST_HOST"],
    # Big thresholds: nothing flushes on its own during the test window.
    flush_at=10000,
    flush_interval=300,
)

# Queued in the master, never flushed: these must NOT appear on the wire.
for i in range(5):
    client.track(f"parent_{i}", "parent_event")


def app(environ, start_response):
    n = parse_qs(environ.get("QUERY_STRING", "")).get("n", ["?"])[0]
    client.track(f"req_{n}", "worker_hit", {"pid": os.getpid()})
    client.flush()
    time.sleep(0.3)  # keep this worker busy so both workers get traffic
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [str(os.getpid()).encode()]
