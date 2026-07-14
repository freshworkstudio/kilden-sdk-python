# Contributing

Behavior in this SDK is governed by
[kilden-sdk-spec](https://github.com/freshworkstudio/kilden-sdk-spec) — the
spec, its test vectors and its mock capture server are the authority. A PR
that changes behavior without a matching spec change will be rejected; open
the conversation on the spec repo first. Bug fixes, typing improvements and
docs are welcome directly.

## Setup

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -m "not integration"     # unit tests
.venv/bin/ruff check . && .venv/bin/mypy  # lint + types
```

Integration tests need Go (for the spec's mock server) and a checkout of
kilden-sdk-spec next to this repo (or `KILDEN_SPEC_DIR`):

```sh
.venv/bin/pytest            # full suite, includes the gunicorn fork test
```

## Questions

Use [Discussions](https://github.com/freshworkstudio/kilden-sdk-python/discussions);
answers there stay searchable.
