"""Contract 9 under a real preforking server: gunicorn --preload, two sync
workers, events tracked from both, inherited parent queue discarded."""

import os
import pathlib
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def gunicorn_app(mock):
    gunicorn = pathlib.Path(sys.executable).parent / "gunicorn"
    if not gunicorn.exists():
        pytest.skip("gunicorn not installed")
    port = free_port()
    env = os.environ.copy()
    env["KILDEN_TEST_HOST"] = mock.base
    env["PYTHONPATH"] = str(REPO_ROOT)
    # macOS-only test-harness detail: the ObjC runtime kills forked children
    # when the parent process had threads (our SDK worker). Linux — where CI
    # runs — is unaffected.
    env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    proc = subprocess.Popen(
        [
            str(gunicorn),
            "--preload",
            "--workers", "2",
            "--bind", f"127.0.0.1:{port}",
            "tests.integration.wsgi_app:app",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            urllib.request.urlopen(f"{base}/?n=warmup", timeout=0.5)
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("gunicorn did not come up")
    yield base
    proc.terminate()
    proc.wait(timeout=10)


def test_fork_safety_under_gunicorn(mock, gunicorn_app):
    worker_pids: set = set()
    errors: list = []

    def hit(n: int) -> None:
        try:
            with urllib.request.urlopen(f"{gunicorn_app}/?n={n}", timeout=10) as resp:
                worker_pids.add(resp.read().decode())
        except Exception as e:
            errors.append(e)

    # Concurrent waves so both sync workers serve traffic (each request
    # holds its worker for ~0.3s).
    threads = [threading.Thread(target=hit, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(worker_pids) == 2, f"expected traffic on 2 workers, saw {worker_pids}"

    events = mock.captured()["events"]
    hits = [e for e in events if e["event"] == "worker_hit"]
    parents = [e for e in events if e["event"] == "parent_event"]

    # Every request event arrived exactly once (warmup + 8), from both pids.
    ns = sorted(e["distinct_id"] for e in hits)
    assert len(ns) == len(set(ns)), f"duplicated events: {ns}"
    assert {f"req_{n}" for n in range(8)} <= set(ns)
    pids = {e["properties"]["pid"] for e in hits}
    assert len(pids) == 2, f"events came from {pids}"

    # The inherited parent queue was discarded, not double-sent: the master
    # never flushes within the test window, so any parent_event on the wire
    # means a worker sent inherited events.
    assert parents == [], f"inherited events leaked from a worker: {parents}"
