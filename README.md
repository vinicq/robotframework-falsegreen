# robotframework-falsegreen

[![CI](https://github.com/vinicq/robotframework-falsegreen/actions/workflows/ci.yml/badge.svg)](https://github.com/vinicq/robotframework-falsegreen/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/robotframework-falsegreen.svg)](https://pypi.org/project/robotframework-falsegreen/)
[![Python](https://img.shields.io/pypi/pyversions/robotframework-falsegreen.svg)](https://pypi.org/project/robotframework-falsegreen/)
[![Downloads](https://img.shields.io/pypi/dm/robotframework-falsegreen.svg)](https://pypistats.org/packages/robotframework-falsegreen)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**One problem, one tool: the false positive.** robotframework-falsegreen finds Robot Framework
tests that pass green without protecting anything - tests that let broken behavior
through because no keyword verifies anything, the failure is swallowed, the check is
always true, or the test is skipped.

Deterministic static scan over the official Robot Framework parser
(`robot.api.get_model`) - no execution. Sibling of
[falsegreen](https://github.com/vinicq/falsegreen) (Python/pytest) and
[falsegreen-js](https://github.com/vinicq/falsegreen-js) (JS/TS). The semantic,
intent-based pass lives in [falsegreen-skill](https://github.com/vinicq/falsegreen-skill).

**The falsegreen family:** [falsegreen](https://github.com/vinicq/falsegreen) (Python/pytest) · [falsegreen-js](https://github.com/vinicq/falsegreen-js) (JS/TS) · **robotframework-falsegreen** (Robot Framework) · [falsegreen-skill](https://github.com/vinicq/falsegreen-skill) (semantic LLM pass).

## Why

A green Robot suite is not proof of correctness. A test case can run keywords and never
call a verification keyword; a `Run Keyword And Ignore Error` can absorb the failure; a
`Should Be True    ${TRUE}` can never fail. This tool flags the patterns a parser can
prove, before they reach review.

## Install

```bash
pip install robotframework-falsegreen
```

## Usage

```bash
rffalsegreen                  # scan cwd
rffalsegreen tests/           # scan a path
rffalsegreen --format json    # machine-readable output (--json is an alias)
rffalsegreen --format sarif   # SARIF 2.1.0 for GitHub code scanning
rffalsegreen --format junit   # JUnit XML for a CI test report
rffalsegreen --output report.sarif  # write to a file
rffalsegreen --output .falsegreen/  # write report.<ext> into a directory
rffalsegreen --config-audit   # audit the Robot run config (project-layer PL codes)
rffalsegreen --disable C16    # turn off specific codes
```

`--format` selects the output shape: `text` (default), `json`, `sarif`, or `junit`. SARIF 2.1.0 (tool name `robotframework-falsegreen`) maps confidence to severity - HIGH to `error`, LOW to `warning`, off/info to `note` - and tags each result with its judgment family and pyramid level, so GitHub code scanning can group and filter findings. JUnit XML emits one testcase per finding: HIGH becomes a `<failure>`, anything lower becomes a `<skipped>`. `--json` stays as an alias for `--format json` and keeps its existing envelope (`tool` / `version` / `judgments` / `findings`).

Each finding is reported with its pyramid level (unit / integration / e2e, read from the suite's imported libraries) and a one-line fix hint, and the text summary breaks the findings down by level and lists the most common fixes. `--output` takes a file or a directory: an extension-less or trailing-slash path (e.g. `.falsegreen/`) receives `report.<ext>` for the chosen format (`report.sarif`, `report.xml` for JUnit). Reports are run artifacts; keep the output directory gitignored.

### Baseline (adopt on a suite that already has findings)

To add the scanner to a suite with pre-existing findings without a wall of red, record a baseline and then fail only on new findings:

```bash
rffalsegreen --write-baseline    # record current findings to .falsegreen-baseline.json
rffalsegreen --baseline          # scan, suppressing everything in the baseline
```

Both flags take an optional path (default `.falsegreen-baseline.json`). The baseline fingerprints a finding by content - `sha1(relative path, code, test/keyword name, detail)` with no line number - so it survives edits that shift a test up or down the file. Commit the baseline so CI sees the same set. A new false-green that is not in the baseline still fails the run; shrink the baseline as you fix the recorded ones.

`--config-audit` is a separate mode: instead of scanning suites, it reads the Robot run config (`robot.toml`, `pyproject.toml` `[tool.robot]`, `*.args` argument files) and reports `PL9` - a `--skiponfailure` / `--noncritical` option that turns a failing test into a non-fatal pass (legacy, removed in RF 4+). The per-file scan cannot see run config.

For the layer no static scan reaches (does a green test fail when the code is wrong?), Robot has no standard mutation tester, so that check is manual review; the semantic [falsegreen-skill](https://github.com/vinicq/falsegreen-skill) covers the intent-level cases.

Exit code: `0` clean, `10` low-confidence only, `20` high-confidence present. Wire exit
`20` into CI to block the merge.

## What it detects

The oracle in Robot is the **verification keyword**. The scanner recognizes them across
libraries (the `Should` convention plus library-specific forms: SeleniumLibrary
`Element Should Be Visible`, Browser's assertion engine `Get Text  sel  ==  expected`,
RESTinstance schema keywords, DatabaseLibrary `Row Count Should Be Equal`, custom
`Verify*`/`Assert*` keywords). A test with none of them verifies nothing.

| Code | Confidence | What it flags |
|---|---|---|
| C2  | high | empty test case, task, or keyword (no keywords run) |
| C2b | low  | runs keywords but no verification keyword (no oracle) |
| C3  | high | `Run Keyword And Ignore Error`/`Return Status`, or a `TRY/EXCEPT` that swallows the failure, leaves the status never asserted |
| C5  | high | always-true (`Should Be True  ${TRUE}`, `Should Be Equal` with equal literals) |
| C6  | low  | weak check — `Should Be True` on a bare variable (truthiness only, not a comparison) |
| C7  | high | self-compare (`Should Be Equal  ${x}  ${x}`) |
| C9  | low  | `Run Keyword And Expect Error` with a catch-all pattern (`*`, `GLOB:*`) — accepts any error |
| C16 | low  | `Sleep` used as synchronization (timing dependence) |
| C20 | high | verification after a `[Return]`/`Return From Keyword`/`Fail`/`Pass Execution` in the same block — a dead step that never runs |
| C21 | low  | verification only runs conditionally (inside `IF` / `Run Keyword If`) — it may never execute |
| C23 | low  | hard-coded IP-address URL in test data (`http://10.0.0.5:8080`) — environment coupling |
| C32 | low  | skipped test (`robot:skip` / `Skip`) |
| C37 | low  | duplicate data row in a `[Template]` — the same scenario runs twice, no extra coverage |
| CC  | low  | commented-out verification keyword (`# Should Be Equal ...`) — the oracle is switched off |
| R1  | high | `Pass Execution` forces the test green regardless of any check |
| R2  | low  | user keyword named like a verifier (`Verify`/`Assert`/`Should`...) but its body verifies nothing — a hollow oracle |
| R3  | high | `*** Test Cases ***` inside a `.resource` file — invalid; the cases never run |
| R4  | high | `No Operation` is the only step — the test/task/keyword does nothing |
| R5  | high | `[Template]` with no data rows — the templated test runs zero cases |
| R6  | low  | `Should Be True` on a string literal (not an expression) — a non-empty string is always truthy, so it never fails |
| R7  | low  | templated test whose in-file `[Template]` keyword contains no verification — every generated case runs without an oracle (only when the keyword resolves in the same file) |

Scans `*** Test Cases ***`, `*** Tasks ***` (RPA), and `*** Keywords ***` definitions in
both `.robot` and `.resource` files. R2 catches the root cause of a missed C2b: a test
calls `Verify Login` and looks protected, but that keyword never asserts anything.

### Opt-in: maintainability group (default off)

Not false-green - the test still verifies - so off by default. Enable with `--diagnostics`.
Three groups, mirroring `falsegreen` and `falsegreen-js`: `false-positive` (C*/R*, on),
`diagnostic` (D*, opt-in), `coupling` (M*, opt-in).

| Code | Group | What it flags |
|---|---|---|
| D2 | diagnostic | control flow (`IF`/`FOR`/`WHILE`/`TRY`) at the test/task level (the guide advises against it) |
| M2 | coupling | test/task with too many steps (guide suggests max ~10) |

```bash
rffalsegreen --diagnostics    # include D*/M* as warnings
```

Codes share ids with the sibling scanners where the concept matches (C2/C2b/C3/C5/C7/C9/C16/C20/C21/C32/C37/CC).
`R*` are Robot-specific. A Browser `Get` keyword with no assertion operator is a plain getter, so a
test whose only step is `Get Text  h1` surfaces as no-verification (C2b). The consolidated catalog's
Robot ids map onto these: RF3 is C3 (here it also catches the form where the status is captured in a
variable but never asserted), RF17 is R6, RF18 is R5, RF20 is C7.

## Test levels (the pyramid)

rffalsegreen scans Robot suites at every level of the pyramid. Discovery is
level-agnostic - it reads any `.robot`/`.resource` - but a few codes are read in light of
the level, so a valid pattern at one level is not flagged at another.

- **Unit:** keyword logic with the boundaries doubled. The oracle is a `Should` keyword.
- **Integration (API and database):** API tests through RequestsLibrary and RESTinstance
  (the schema keywords count as the oracle), database tests through DatabaseLibrary
  (`Row Count Should Be Equal`, `Check If Exists In Database`). These hit a real endpoint or
  datastore on purpose, so the request or row IS the verification at that level.
- **E2E:** the Browser library and SeleniumLibrary/Appium. The page assertion
  (`Page Should Contain`, `Get Text ... == ...`) is the oracle; the presence of a rendered
  element is a real check at this level, not a weak one.

A real API or database hit inside a test that claims to be a unit test is itself the smell
(environment coupling, mystery guest), not the level of the test. C23 flags the strongest
form: a hard-coded IP-address endpoint.

## Scope and honesty

Static scan: it owns what the keyword structure proves. It does not run the suite, so it
cannot see runtime-only smells (Test Run War, order dependence across suites). Whether the
expected value contradicts the intended behavior is semantic and belongs to
`falsegreen-skill`. Precision over recall: `C2b` is low-confidence because a custom keyword
may assert internally without `Should` in its name.

### Not implemented, on purpose

Some catalog codes are left out because the gain is not worth the false positives, or because
another tool already owns them. Listing them is part of the scope:

- **RF16 (`Wait Until Keyword Succeeds`)** — a retry wrapper. Legitimate retry around genuinely
  asynchronous behavior is common and idiomatic, so flagging every use would be mostly noise. The
  false-positive rate is too high for a static rule; this is a judgment call left to review.
- **Hygiene already covered by [Robocop](https://github.com/MarketSquare/robotframework-robocop)** —
  RF6 (dead keyword, cross-file), RF8 (unused argument), RF13 (duplicate name), RF14 (missing
  documentation), RF15 (too long), RF19 (unused import). These are maintainability lint, not
  false-green, and Robocop detects them well. Run Robocop alongside this scanner; there is no reason
  to reimplement them.

### C-codes with no idiomatic Robot form

Three Python/JS sibling codes have no clean Robot equivalent and are intentionally skipped:

- **C8 (exact float equality)** — Robot test data is untyped text, so a value cannot be proven to be
  a float from the parse tree (`Should Be Equal As Numbers` even takes a `precision` argument). Any
  rule here would guess, with a high false-positive rate.
- **C18 (compare a stringified value to a literal)** — Robot has no `str()`/`repr()` round-trip
  concept; everything is already a string. There is no structural signal to key on.

C9 (broad error assertion) and C20 (dead step after a terminator) *do* have idiomatic Robot forms
(`Run Keyword And Expect Error    *` and a verification after `[Return]`/`Fail`), so both are
implemented above. Robot has no standard mutation tester, so the semantic layer (does a green test
fail when the code is wrong?) stays manual review; the intent-level cases live in
[falsegreen-skill](https://github.com/vinicq/falsegreen-skill).

## License

MIT, Vinicius Queiroz.

## Contributors ✨

Thanks to the people who keep false-green tests out of real suites ([emoji key](https://allcontributors.org/docs/en/emoji-key)):

<!-- ALL-CONTRIBUTORS-BADGE:START - Do not remove or modify this section -->
[![All Contributors](https://img.shields.io/badge/all_contributors-2-orange.svg?style=flat-square)](#contributors-)
<!-- ALL-CONTRIBUTORS-BADGE:END -->

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://vinicq.github.io/md-bridge/"><img src="https://avatars.githubusercontent.com/u/78210890?v=4?s=100" width="100px;" alt="Vinicius Queiroz"/><br /><sub><b>Vinicius Queiroz</b></sub></a><br /><a href="https://github.com/vinicq/robotframework-falsegreen/commits?author=vinicq" title="Code">💻</a> <a href="https://github.com/vinicq/robotframework-falsegreen/commits?author=vinicq" title="Documentation">📖</a> <a href="#ideas-vinicq" title="Ideas, Planning, & Feedback">🤔</a> <a href="#maintenance-vinicq" title="Maintenance">🚧</a> <a href="#infra-vinicq" title="Infrastructure (Hosting, Build-Tools, etc)">🚇</a> <a href="https://github.com/vinicq/robotframework-falsegreen/commits?author=vinicq" title="Tests">⚠️</a> <a href="#research-vinicq" title="Research">🔬</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/homesellerq-coder"><img src="https://avatars.githubusercontent.com/u/294912019?v=4?s=100" width="100px;" alt="Home Seller"/><br /><sub><b>Home Seller</b></sub></a><br /><a href="https://github.com/vinicq/robotframework-falsegreen/commits?author=homesellerq-coder" title="Code">💻</a> <a href="https://github.com/vinicq/robotframework-falsegreen/commits?author=homesellerq-coder" title="Documentation">📖</a> <a href="https://github.com/vinicq/robotframework-falsegreen/commits?author=homesellerq-coder" title="Tests">⚠️</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->

New contributors are added automatically; the table also recognizes non-code work (docs, ideas, infrastructure, tests, research) via the [all-contributors](https://allcontributors.org) spec.
