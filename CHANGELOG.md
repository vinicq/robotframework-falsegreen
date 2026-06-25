# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `--format text|json|sarif|junit` (parity with the Python `falsegreen`). `--json` stays as
  an alias for `--format json` and keeps its envelope (`tool`/`version`/`judgments`/`findings`).
  SARIF 2.1.0 carries the tool name `robotframework-falsegreen`, maps confidence to severity
  (HIGH to `error`, LOW to `warning`, off/info to `note`), and tags each result with its
  judgment family, group, and pyramid level. JUnit XML emits one testcase per finding: HIGH is
  a `<failure>`, anything lower is a `<skipped>`. `--output` resolves the extension per format
  (`report.sarif`, `report.xml` for JUnit).
- `--baseline [PATH]` / `--write-baseline [PATH]` (default `.falsegreen-baseline.json`): adopt
  the scanner on a suite that already has findings, then fail only on new ones. The fingerprint
  is content-based - `sha1(relative path, code, test/keyword name, detail)[:16]`, no line number
  - so it survives edits that shift a test up or down the file. `--write-baseline` records the
  current findings and exits 0; `--baseline` suppresses every recorded fingerprint.

## [0.2.0] - 2026-06-23

### Changed

- **Renamed to `robotframework-falsegreen`** to fit the Robot Framework ecosystem. The PyPI
  package and the GitHub repo are now `robotframework-falsegreen` (the `robotframework-`
  prefix convention), and the package carries the `Framework :: Robot Framework :: Tool`
  classifier. The CLI command is `rffalsegreen` (short, mirroring `rfbrowser`); the import
  package stays `falsegreen_robot`. Pre-release, so there is no PyPI migration; the old
  GitHub URL redirects.

### Added

- `--config-audit` mode (project layer): reads the Robot run config (`robot.toml`,
  `pyproject.toml` `[tool.robot]`, `*.args` argument files) and reports PL9 - a
  `--skiponfailure`/`--noncritical` option that turns a failing test into a non-fatal pass
  (legacy, removed in RF 4+). Findings carry level `project` and a fix hint. TOML sources need
  a TOML reader (`tomllib` on 3.11+, else `tomli`); the `*.args` scan works on every version.
  README notes that Robot has no standard mutation tester, so the F7 layer is manual review.
- New codes: R3 (`*** Test Cases ***` inside a `.resource` file), R4 (`No Operation` as the
  only step), R5 (`[Template]` with no data rows). C2 now also flags an empty user keyword
  (only settings, no steps). C23 (low): a hard-coded IP-address URL in test data, restricted
  to IP literals so hostname URLs common in E2E are not flagged.
- Documented test-pyramid coverage: unit, integration (API and database), and E2E. The
  scanner is level-agnostic; some codes are interpreted per level to keep precision.
- Status report output: every finding now carries its pyramid level (unit / integration /
  e2e, detected from the suite's imported libraries: SeleniumLibrary/Browser/AppiumLibrary
  are e2e, RequestsLibrary/RESTinstance/DatabaseLibrary are integration) and a one-line fix
  hint. The text summary adds a per-level breakdown and the top fixes by frequency; JSON
  gains `level` and `fix` fields.
- `--output` flag: write to a file, or pass a directory (e.g. `.falsegreen/`) to get
  `report.<ext>` for the chosen format. Parent directories are created as needed.

## [0.1.0] - 2026-06-22

### Added

- `.resource` files and `*** Keywords ***` definitions are now scanned (in both `.robot`
  and `.resource`). New code R2: a user keyword named like a verifier (Verify/Assert/Should)
  whose body contains no verification — a hollow oracle, the root cause of missed C2b.
  Call-level smells (C5/C7/C16) are also detected inside user keywords.
- Three groups (`false-positive` / `diagnostic` / `coupling`), like the sibling scanners.
  Opt-in maintainability group (default off, `--diagnostics`): D2 (control flow at the
  test/task level), M2 (too many steps).
- RPA support: scans `*** Tasks ***` in addition to `*** Test Cases ***`.
- Initial release. Deterministic static scanner for false-positive Robot Framework
  tests, built on the official `robot.api.get_model` parser (no execution).
- Detection codes: C2 (empty test), C2b (no verification keyword), C3 (swallowed
  `Run Keyword And Ignore Error`/`Return Status`), C5 (always-true), C7 (self-compare),
  C6 (weak Should Be True on a bare variable), C16 (`Sleep` as synchronization), C21 (conditional-only verification), C32 (skipped), R1 (Pass Execution forced green). C3 also covers native TRY/EXCEPT swallow. Codes share ids with the sibling
  scanners where the concept matches.
- Verification-keyword recognition across libraries: the `Should` convention plus
  SeleniumLibrary/AppiumLibrary, Browser's assertion engine (`Get ... == expected`),
  RESTinstance schema keywords, DatabaseLibrary, RequestsLibrary, and custom
  `Verify*`/`Assert*`/`Validate*`/`Check *` keywords.
- CLI: paths, `--json`, `--disable`, `--version`. Exit codes 0/10/20.

[Unreleased]: https://github.com/vinicq/robotframework-falsegreen/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/vinicq/robotframework-falsegreen/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/vinicq/robotframework-falsegreen/releases/tag/v0.1.0
