# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project config file (#50): `[tool.falsegreen]` in `pyproject.toml`, or a whole-file
  `.falsegreen.toml` root table when there is no `[tool.falsegreen]` (first found wins, no
  merge). Four keys: `disable` (codes, additive with `--disable`), `diagnostics` (bool, OR
  with `--diagnostics`), `long_test` (int, overrides the long-test step threshold), and
  `verify_keywords` (custom verifier patterns, see below). Unknown keys and codes warn to
  stderr and are skipped; the run does not fail. CLI flags override or extend the file. This
  is separate from `--config-audit`, which reads the Robot run config (`[tool.robot]`).
- `verify_keywords` config (#54): custom verification-keyword patterns. A keyword whose full
  normalized name contains one of the patterns counts as an oracle, so `Confirm Balance` or
  `Expect Response Ok` no longer surface as false `C2b`/`C21`/`R2`/`R7`. Opt-in: with no
  patterns the behavior is unchanged. The match only suppresses a false positive, it never
  creates a finding.
- `C44` (high): a library assertion provably true for any runtime value. Covers
  `Should Contain  ${x}  ${EMPTY}` (every string contains the empty string),
  `Should Not Be Empty  ${TRUE}` (a constant is never empty), `Should Be Empty  ${EMPTY}`,
  and `Length Should Be` against a fixed length (the empty literal, or a subject assigned a
  literal by an immediately-preceding `Set Variable`). Two free variables, a runtime-computed
  length, and `Should Be True  ${EMPTY}` (that is `R6`/`C6`) are excluded, and `C44` is
  suppressed where `C5`/`C6`/`R6` already own the line. (#53)
- `examples/` tree (#48): a worked sample for every emitted code, a BAD case the scanner flags
  paired with a CLEAN look-alike one token away that it leaves alone. Files are grouped by theme
  (`effectiveness`, `execution`, `nondeterminism`, `dependency`, `templates`), with
  `resource_file.resource` for `R3` and `diagnostics.robot` for the opt-in `D2`/`M2` group.
  `tests/test_examples.py` scans each file with `analyze_file` and asserts every code fires in
  its file, with a drift guard that fails if a new code lands in the catalog without an example.
  The self-scan (`python -m falsegreen_robot src tests`) does not include `examples/`. The
  config-audit-only `PL9` scans the Robot run config rather than a `.robot` file, so it has no
  test-file example.

### Changed

- `C5` broadened (#47): a `Set Variable If` with a constant-true guard whose assigned value
  flows into the expected side of a later `Should Be Equal` is now flagged. The oracle is
  pinned to a constant the test fixed, so the comparison is a tautology. A runtime-variable
  guard is normal branching and stays silent, and the rule fires only when the assigned name
  is proven to reach an assertion's expected argument.

## [0.3.0] - 2026-06-28

### Added
- Inline suppression: `# falsegreen: ignore` on a line silences every code there, and
  `# falsegreen: ignore[C16,C20]` silences only the listed codes. Same token and bracket
  syntax as falsegreen (Python) and falsegreen-js; scoped to the line, exact-token only (#49).
- `C16` broadened beyond `Sleep` to the rest of the non-determinism family: `Get Current Date`
  (clock read), `Generate Random String` (randomness), and an `Evaluate` body that reaches for
  `datetime.`/`random.`/`uuid.` (module access, so a `random_seed` variable is not matched).
  Parity with the JS `new Date()`/`crypto.*` and Python `uuid`/`secrets` broadening (#63).

### Fixed
- `C2b` no longer false-positives on `Wait Until Keyword Succeeds  <retry>  <interval>
  Should Be Equal ...`: `is_verification` now peeks inside the retry wrapper and recurses
  on the inner keyword, so retrying a real assertion counts as an oracle. Retrying a bare
  action (`... Click ...`) still has no oracle and stays flagged (#46).
- `CC` no longer fires on prose comments that merely start with a verification verb
  (`# Validate that...`, `# Should we keep this?`): the verb must be followed by a keyword-call
  shape - more capitalized name words then a `\s{2,}`/tab arg separator, a `${`/`@{`/`&{`
  variable, or end-of-line. `# Should Be Equal    ${a}    ${b}` and `# Verify Login` still fire (#61).
- Inline `ignore[code]` is now case-insensitive: `ignore[c16]` suppresses the `C16` a finding
  carries (bracket codes are upper-cased on parse). Mirrors the Python sibling (#62).
- An inline `# falsegreen: ignore` on a continuation (`...`) row is now folded onto the owning
  statement's first physical line, where the finding is reported, so the suppression applies (#64).

### Docs
- README documents why Robot has no `C48` (dark-patch): untyped test data means a variable cannot
  be proven to be a test-mode flag from the parse tree, so the false-positive ceiling is too high (#66).
- Added the `PL9` row to the CREDITS code-to-source map; fixed the CHANGELOG footer compare
  links (`[0.3.0]`, and `[Unreleased]` now diffs from v0.3.0) (#65).

### Fixed (earlier in the 0.3.0 cycle)
- C9 no longer treats EQUALS:* / STARTS:* as catch-alls and now flags the regex catch-all REGEXP:.*; the registry message was corrected (#41).
- C20: Pass Execution If / Return From Keyword If count as terminators only with a constant-true guard; R6 excludes falsy literals (#41).
- An in-file dotted keyword (e.g. api.GET) is a local keyword and is not prefix-stripped into a library call (#43).


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

[Unreleased]: https://github.com/vinicq/robotframework-falsegreen/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/vinicq/robotframework-falsegreen/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/vinicq/robotframework-falsegreen/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/vinicq/robotframework-falsegreen/releases/tag/v0.1.0
