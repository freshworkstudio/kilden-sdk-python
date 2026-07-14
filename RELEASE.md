# Releasing

Releases are cut from tags; `release.yml` builds and uploads to PyPI using
the `PYPI_TOKEN` repository secret.

## One-time setup (pending)

`PYPI_TOKEN` is **not configured yet** — the `kilden` name on PyPI is
unclaimed. First release must be done by a human:

```sh
python -m venv .venv && .venv/bin/pip install build twine
.venv/bin/python -m build
.venv/bin/twine check dist/*
# with a PyPI API token for an account that will own the `kilden` name:
TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-… .venv/bin/twine upload dist/*
```

Then store the token as the `PYPI_TOKEN` actions secret so tags publish
automatically:

```sh
gh secret set PYPI_TOKEN --repo freshworkstudio/kilden-sdk-python
```

## Cutting a release

1. Update `src/kilden/version.py` and `pyproject.toml` (`version`), update
   `CHANGELOG.md`.
2. `git tag v0.x.y && git push origin v0.x.y`.

Note PEP 440: the git tag `v0.1.0-alpha.1` corresponds to the Python
version `0.1.0a1`.
