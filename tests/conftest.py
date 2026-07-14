import json
import os
import pathlib
import shutil
import socket
import subprocess
import time
import urllib.request

import pytest

_DEFAULT_SPEC = pathlib.Path(__file__).resolve().parents[2] / "kilden-sdk-spec"
SPEC_DIR = pathlib.Path(os.environ.get("KILDEN_SPEC_DIR", _DEFAULT_SPEC))


@pytest.fixture(scope="session")
def spec_dir() -> pathlib.Path:
    if not SPEC_DIR.exists():
        pytest.skip(f"kilden-sdk-spec checkout not found at {SPEC_DIR} (set KILDEN_SPEC_DIR)")
    return SPEC_DIR


@pytest.fixture(scope="session")
def vectors(spec_dir):
    def load(name: str):
        with open(spec_dir / "vectors" / name) as f:
            return json.load(f)

    return load


@pytest.fixture(scope="session")
def mock_server(spec_dir, tmp_path_factory):
    """Build and run the spec repo's mock capture server on a free port."""
    if shutil.which("go") is None:
        pytest.skip("go toolchain not available")
    binary = tmp_path_factory.mktemp("mock") / "mockserver"
    subprocess.run(
        ["go", "build", "-o", str(binary), "."],
        cwd=spec_dir / "mockserver",
        check=True,
        capture_output=True,
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([str(binary), "-addr", f"127.0.0.1:{port}"])
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{base}/healthz", timeout=0.2)
            break
        except Exception:
            time.sleep(0.05)
    else:
        proc.kill()
        pytest.fail("mock server did not come up")
    yield base
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture()
def mock(mock_server):
    """The mock server, reset before each test."""

    def call(path: str, payload=None):
        data = json.dumps(payload).encode() if payload is not None else b""
        req = urllib.request.Request(
            f"{mock_server}{path}",
            data=data if payload is not None else None,
            headers={"Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return json.loads(resp.read())

    call("/__mock/reset", {})

    class Mock:
        base = mock_server

        @staticmethod
        def captured():
            return call("/__mock/captured")

        @staticmethod
        def control(path, payload):
            return call(path, payload)

    return Mock
