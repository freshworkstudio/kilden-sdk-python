# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/freshworkstudio/kilden-sdk-python/compare/v0.1.0-alpha.1...HEAD
[0.1.0a2]: https://github.com/freshworkstudio/kilden-sdk-python/compare/v0.1.0-alpha.1...v0.1.0-alpha.2
[0.1.0a1]: https://github.com/freshworkstudio/kilden-sdk-python/releases/tag/v0.1.0-alpha.1
