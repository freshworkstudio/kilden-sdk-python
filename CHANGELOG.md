# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-07-16

First stable release. The public surface and the twelve behavior contracts of
[kilden-sdk-spec](https://github.com/kildenhq/kilden-sdk-spec) are now frozen
under semver: no breaking changes without a major bump.

Graduating out of prerelease also means `pip install kilden` resolves here —
until now a bare install found nothing, since pip skips prereleases by default.

### Fixed

- `IdentitySigner` escapes the JS line separators U+2028/U+2029 the way Go's
  `encoding/json` does (spec §6.1). This only affects byte-identity with the
  frozen vectors and the other SDKs — tokens signed by the previous release
  verify fine, since the signature covers the payload as transmitted.

### Verified

- End-to-end against production ingest, not just the spec's mock server:
  `track`, `identify` and `alias` land with `source=server`, `verified=true`;
  `IdentitySigner` tokens are accepted by the enricher (a no-token control
  lands `verified=false`); `is_enabled` reflects live flag changes.

## [0.1.0a3] - 2026-07-14

### Changed

- Repository moved to the kildenhq org; releases publish to PyPI via OIDC
  trusted publishing.

## [0.1.0a2] - 2026-07-14

### Fixed

- Any 2xx from `/capture` is success; the response body is never parsed
  (spec clarification — a 200 with a corrupt body was retried before).

## [0.1.0a1] - 2026-07-14

### Added

- `Client`: `track`, `identify`, `alias`, `flush`, `close` with bounded
  in-memory queue, background delivery, gzip, and the spec retry policy.
- Fork safety: PID check on enqueue, tested against preforked gunicorn.
- `IdentitySigner`: hand-rolled HS256 over the spec's canonical JSON form,
  byte-identical with every other Kilden SDK.
- Feature flags: `is_enabled` / `get_feature_flag` via `/decide`, 30s LRU
  cache, `person_properties`, `default`.
- Vector runners for kilden-sdk-spec (payload, identity, flag hashing) wired
  into CI against the spec's mock capture server.

[Unreleased]: https://github.com/kildenhq/kilden-sdk-python/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kildenhq/kilden-sdk-python/compare/v0.1.0-alpha.3...v0.1.0
[0.1.0a3]: https://github.com/kildenhq/kilden-sdk-python/compare/v0.1.0-alpha.2...v0.1.0-alpha.3
[0.1.0a2]: https://github.com/kildenhq/kilden-sdk-python/compare/v0.1.0-alpha.1...v0.1.0-alpha.2
[0.1.0a1]: https://github.com/kildenhq/kilden-sdk-python/releases/tag/v0.1.0-alpha.1
