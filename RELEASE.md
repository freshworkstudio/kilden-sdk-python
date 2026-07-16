# Releasing

Releases are cut from `v*` tags; `release.yml` builds, publishes to PyPI via
**OIDC trusted publishing** (no token secret), and creates the GitHub
release with the artifacts attached.

## One-time setup

Register the trusted publisher on PyPI (works before the first upload, as a
*pending* publisher): <https://pypi.org/manage/account/publishing/> →

- PyPI project name: `kilden`
- Owner: `kildenhq` · Repository: `kilden-sdk-python`
- Workflow name: `release.yml` · Environment: (leave empty)

## Cutting a release

1. Bump `version` in `pyproject.toml` and `src/kilden/version.py`
   (PEP 440: git tag `v0.1.0-alpha.3` ↔ version `0.1.0a3`).
2. Update `CHANGELOG.md`.
3. `git tag v0.1.0-alpha.3 && git push origin v0.1.0-alpha.3`.

The workflow does the rest. Manual fallback (needs a PyPI API token):
`python -m build && twine check dist/* && twine upload dist/*`.
