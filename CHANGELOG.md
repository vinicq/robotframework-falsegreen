# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **R7** (low): a templated test whose `[Template]` keyword is a user keyword defined in the
  same file and whose body contains no verification - every generated case runs without an
  oracle. The rule only fires when the keyword resolves in-file; a `[Template]` keyword
  imported from a resource is left alone, since it may verify through a keyword the scanner
  cannot see. A hollow keyword named like a verifier is already R2 on its definition, so the
  templated test is not double-flagged. (issue #32)

### Fixed

- **`Run Keywords` precision** (issue #33): the verification scan now splits a `Run Keywords`
  call on its `AND` separator and checks each segment's keyword, so
  `Run Keywords    Click    AND    Should Be Equal    ${a}    ${b}` is recognized as carrying
  an oracle and no longer falsely flagged C2b. A chain of only actions is still C2b.

### Changed

- **C3 wording** (issue #35): the catalog text now reads "Run Keyword And Ignore Error/Return
  Status, or a TRY/EXCEPT that swallows the failure, leaves the status never asserted" so it
  covers the native `TRY/EXCEPT` swallow case the scanner already detects, not only the
  `Run Keyword And ...` forms.

- New detection codes (issue #19, from the consolidated catalog):
  - **C3 (status form)**: `Run Keyword And Ignore Error` / `Run Keyword And Return Status` whose
    status is captured in a variable that no later step reads. This is the Robot try/except/pass -
    the failure is swallowed even when the test verifies something else. The existing bare-call C3
    (result discarded entirely) is unchanged. (catalog RF3, high)
  - **R6**: `Should Be True` on a string literal (not an expression). A non-empty string is always
    truthy, so the check never fails. A bare `${x}` stays C6, a constant stays C5. (catalog RF17, low)
  - **C9**: `Run Keyword And Expect Error` with a catch-all pattern (`*`, `GLOB:*`, `EQUALS:*`) -
    accepts any error, so a wrong failure still passes. A specific pattern is recognized as a real
    oracle. (low)
  - **C20**: a verification keyword after a terminator (`[Return]`/`Return From Keyword` in a
    keyword, `Fail`/`Pass Execution` in a test) in the same block - a dead step that never runs.
    Each block body is scanned on its own. (high)
  - **C37**: a duplicate data row in a `[Template]` - the same scenario runs twice, no extra
    coverage. (low)
  - **CC**: a commented-out verification keyword (`# Should Be Equal ...`, `# Page Should Contain
    ...`, `# Verify ...`). Raw source scan, since the parser drops comments; a plain prose comment
    is not flagged. (low)
- Scope documented in the README: RF16 (`Wait Until Keyword Succeeds`) is left out (high
  false-positive rate on legitimate retries); the Robocop-covered hygiene codes (RF6/8/13/14/15/19)
  are deferred to Robocop; and C8 (float equality) and C18 (stringified compare) have no idiomatic
  Robot form so they are not ported.
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

### Changed

- Repo community hygiene now matches the `falsegreen` template: README status badges (CI, PyPI,
  Python versions, License), issue templates (`bug_report`, `feature_request`, `config`), a pull
  request template, `CODEOWNERS`, Dependabot for `pip` and `github-actions`, and a release-drafter
  config plus workflow. The release-drafter job is skipped on PRs from forks, where it cannot write.
  (issue #21)

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
