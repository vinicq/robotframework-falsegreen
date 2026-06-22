# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-22

### Added

- Three groups (`false-positive` / `diagnostic` / `coupling`), like the sibling scanners.
  Opt-in maintainability group (default off, `--diagnostics`): D2 (control flow at the
  test/task level), M2 (too many steps).
- RPA support: scans `*** Tasks ***` in addition to `*** Test Cases ***`.
- Initial release. Deterministic static scanner for false-positive Robot Framework
  tests, built on the official `robot.api.get_model` parser (no execution).
- Detection codes: C2 (empty test), C2b (no verification keyword), C3 (swallowed
  `Run Keyword And Ignore Error`/`Return Status`), C5 (always-true), C7 (self-compare),
  C16 (`Sleep` as synchronization), C21 (conditional-only verification), C32 (skipped), R1 (Pass Execution forced green). C3 also covers native TRY/EXCEPT swallow. Codes share ids with the sibling
  scanners where the concept matches.
- Verification-keyword recognition across libraries: the `Should` convention plus
  SeleniumLibrary/AppiumLibrary, Browser's assertion engine (`Get ... == expected`),
  RESTinstance schema keywords, DatabaseLibrary, RequestsLibrary, and custom
  `Verify*`/`Assert*`/`Validate*`/`Check *` keywords.
- CLI: paths, `--json`, `--disable`, `--version`. Exit codes 0/10/20.

[Unreleased]: https://github.com/vinicq/falsegreen-robot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/vinicq/falsegreen-robot/releases/tag/v0.1.0
