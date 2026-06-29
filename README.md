# robotframework-falsegreen

[![CI](https://github.com/vinicq/robotframework-falsegreen/actions/workflows/ci.yml/badge.svg)](https://github.com/vinicq/robotframework-falsegreen/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/robotframework-falsegreen.svg)](https://pypi.org/project/robotframework-falsegreen/)
[![Python](https://img.shields.io/pypi/pyversions/robotframework-falsegreen.svg)](https://pypi.org/project/robotframework-falsegreen/)
[![Downloads](https://img.shields.io/pypi/dm/robotframework-falsegreen.svg)](https://pypistats.org/packages/robotframework-falsegreen)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Docs](https://img.shields.io/badge/docs-online-blue.svg)](https://vinicq.github.io/falsegreen-docs/)

**One problem, one tool: the false positive.** robotframework-falsegreen finds Robot Framework
tests that pass green without protecting anything - tests that let broken behavior
through because no keyword verifies anything, the failure is swallowed, the check is
always true, or the test is skipped.

Deterministic static scan over the official Robot Framework parser
(`robot.api.get_model`) - no execution. Sibling of
[falsegreen](https://github.com/vinicq/falsegreen) (Python/pytest) and
[falsegreen-js](https://github.com/vinicq/falsegreen-js) (JS/TS). The semantic,
intent-based pass lives in [falsegreen-skill](https://github.com/vinicq/falsegreen-skill).

**The falsegreen family** (install the one for your stack):

| Tool | Stack | Install | Package |
|---|---|---|---|
| [falsegreen](https://github.com/vinicq/falsegreen) | Python / pytest | `pip install falsegreen` | [PyPI](https://pypi.org/project/falsegreen/) |
| [falsegreen-js](https://github.com/vinicq/falsegreen-js) | JS / TS | `npm i -D falsegreen-js` (`npx falsegreen-js`) | [npm](https://www.npmjs.com/package/falsegreen-js) |
| **robotframework-falsegreen** | Robot Framework | `pip install robotframework-falsegreen` | [PyPI](https://pypi.org/project/robotframework-falsegreen/) |
| [falsegreen-skill](https://github.com/vinicq/falsegreen-skill) | semantic LLM pass | `npx falsegreen-skill analyze <path>` | [npm](https://www.npmjs.com/package/falsegreen-skill) |

## Quick guide for first-time users

New here? Start with these five sections. They get you from zero to a CI gate. The deeper reference (every code, the scope rules, the research) follows after.

### What it does

robotframework-falsegreen reads your Robot Framework suites and finds the test cases that pass green without verifying anything. A test can run keywords, report success, and never call a single verification keyword, so a bug ships and the green report lies about it. The scanner reads the `.robot` and `.resource` files only (it never runs them) and flags the cases a parser can prove have no oracle, an always-true check, a swallowed failure, or a skip.

A test it flags, and the fix:

```robotframework
*** Test Cases ***
# BAD: runs keywords, verifies nothing. Passes even if login is broken.
Login Succeeds
    Open Browser    https://app.example.com
    Input Text    id:user    alice
    Click Button    Login

# CLEAN: adds a verification keyword. Fails if the page does not land.
Login Succeeds
    Open Browser    https://app.example.com
    Input Text    id:user    alice
    Click Button    Login
    Page Should Contain    Welcome, alice
```

### Install

```bash
pip install robotframework-falsegreen
```

Needs Python 3.8 or newer. It depends on `robotframework` (the official parser it reads your suites with), pulled in automatically.

### Quick start

Point it at your suite folder:

```bash
rffalsegreen tests/
```

Run on the `Login Succeeds` example above and you get:

```
login.robot
  low  C2b  L2    Login Succeeds  runs keywords but no verification keyword (no oracle)
           level: unit   fix: add a verification keyword (Should..., a library assertion)

0 high, 1 low. https://github.com/vinicq/robotframework-falsegreen
By level: unit:1
Top fixes:
  C2b (1): add a verification keyword (Should..., a library assertion)
```

How to read that finding:

- `login.robot` then `L2` - the file and line of the test case.
- `C2b` - the code. C2b is "runs keywords but no verification keyword". The catalog (below) explains every code.
- `Login Succeeds` - the test case name.
- `level: unit` - which level of the test pyramid this suite sits at.
- `fix:` - the one-line hint. Here: add a verification keyword.

### Common options

```bash
rffalsegreen tests/ --json          # machine-readable JSON instead of text
rffalsegreen tests/ --format sarif  # text (default) | json | sarif | junit
rffalsegreen tests/ --disable C16   # turn specific codes off
```

Exit codes wire it into CI: `0` clean, `10` low-confidence findings only, `20` at least one high-confidence finding. Block the build on `20`.

GitHub Actions:

```yaml
name: rffalsegreen
on: [push, pull_request]
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.x" }
      - run: pip install robotframework-falsegreen
      - run: rffalsegreen tests/   # exit 20 fails the job
```

### What the codes mean

Each finding carries a code and a confidence. HIGH codes are near-certain and block the commit; LOW codes warn and want a human look. Codes shared with the Python and JS scanners keep the same id (`C2b` no oracle, `C5` always true, `C7` self-compare); `R*` codes are Robot-specific (`R1` `Pass Execution` forces green, `R8` the only check sits in `[Setup]`). The full list is in the [What it detects](#what-it-detects) table below and the [online docs](https://vinicq.github.io/falsegreen-docs/).

## Usage and configuration reference

The quick guide above gets you running. This section is the complete reference: every install channel, every flag, every output format, every config knob, and the CI recipes. All command output shown here is captured from a real run, not invented.

### Install

| Channel | Command | When to use |
|---|---|---|
| pip (global or venv) | `pip install robotframework-falsegreen` | the normal install; adds the `rffalsegreen` command |
| pipx (isolated) | `pipx install robotframework-falsegreen` | keep it off your project's dependency tree |
| pipx run (no install) | `pipx run --spec robotframework-falsegreen rffalsegreen tests/` | one-off, latest release from PyPI |
| from source | `pip install -e .` in a clone | hacking on the scanner |

Version floor: **Python 3.8 or newer**. It depends on `robotframework` (>=4.0), the official parser it reads your suites with, pulled in automatically. Pin a version in CI with `pip install robotframework-falsegreen==0.6.2`.

### Invocation

```bash
rffalsegreen                        # scan the current directory
rffalsegreen tests/                 # scan a suite folder
rffalsegreen tests/login.robot      # scan a single suite file
rffalsegreen tests/ resources/      # scan several paths
python -m falsegreen_robot.scanner tests/   # module form, identical behaviour
```

There is no stdin mode and no `--staged` flag: pass file or directory paths (or nothing, which scans the cwd). Discovery reads `.robot` and `.resource` files; everything else is skipped.

### Output formats

`--format text|json|sarif|junit|robot` selects the shape (default `text`). `--json` is a shorthand for `--format json`. `--output PATH` writes to a file instead of stdout; a directory or trailing-slash path (`.falsegreen/`) receives `report.<ext>`. The `robot` format is unique to this scanner: it groups findings under each test case.

Fixture used for every sample below (`login.robot`):

```robotframework
*** Test Cases ***
Login Succeeds
    Log    Opening browser
    Log    Clicking login

Always Green
    Should Be True    ${TRUE}
```

**text** (default):

```
login.robot
  low  C2b  L2    Login Succeeds  runs keywords but no verification keyword (no oracle)
           level: unit   fix: add a verification keyword (Should..., a library assertion)
  HIGH C5   L7    Always Green  always-true check (Should Be True ${TRUE} / Should Be Equal with equal literals, or a constant-true Set Variable If feeding the expected side)
           Should Be True on a constant
           level: unit   fix: compare against an independent expected value, not a constant

1 high, 1 low. https://github.com/vinicq/robotframework-falsegreen
By level: unit:2
Top fixes:
  C2b (1): add a verification keyword (Should..., a library assertion)
  C5 (1): compare against an independent expected value, not a constant
```

**robot** (`--format robot`): the same findings grouped per test case, no `level` line.

```
login.robot
  Always Green
    HIGH C5   L7    always-true check (Should Be True ${TRUE} / Should Be Equal ...)
           Should Be True on a constant
           fix: compare against an independent expected value, not a constant
  Login Succeeds
    low  C2b  L2    runs keywords but no verification keyword (no oracle)
           fix: add a verification keyword (Should..., a library assertion)

1 high, 1 low. https://github.com/vinicq/robotframework-falsegreen
```

**json** (`--json` or `--format json`): an envelope with `tool`, `version`, the judgment legend, and a `findings` array. Each finding carries the `test` case name.

```json
{
  "tool": "robotframework-falsegreen",
  "version": "0.6.2",
  "judgments": { "J1": "does the verification run?", "...": "..." },
  "findings": [
    {
      "file": "login.robot",
      "line": 2,
      "test": "Login Succeeds",
      "code": "C2b",
      "confidence": "low",
      "judgment": "J1",
      "title": "runs keywords but no verification keyword (no oracle)",
      "detail": "",
      "level": "unit",
      "fix": "add a verification keyword (Should..., a library assertion)"
    }
  ]
}
```

**sarif** (`--format sarif`): SARIF 2.1.0 for GitHub code scanning. HIGH maps to `error`, LOW to `warning`, off/info to `note`; each result is tagged with its judgment family and group. Abridged:

```json
{
  "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
  "version": "2.1.0",
  "runs": [
    {
      "tool": { "driver": {
        "name": "robotframework-falsegreen",
        "version": "0.6.2",
        "rules": [
          { "id": "C5", "defaultConfiguration": { "level": "error" },
            "properties": { "tags": ["J2", "group:false-positive"] } }
        ]
      } },
      "results": [
        { "ruleId": "C2b", "level": "warning",
          "message": { "text": "runs keywords but no verification keyword (no oracle)" } }
      ]
    }
  ]
}
```

**junit** (`--format junit`): JUnit XML. HIGH becomes a `<failure>`, lower findings become `<skipped>`.

```xml
<?xml version="1.0" encoding="utf-8"?>
<testsuites name="robotframework-falsegreen" tests="2" failures="1" skipped="1" errors="0"><testsuite name="robotframework-falsegreen" tests="2" failures="1" skipped="1" errors="0"><testcase classname="robotframework-falsegreen.C2b" name="C2b login.robot:2"><skipped message="runs keywords but no verification keyword (no oracle)  login.robot:2" /></testcase><testcase classname="robotframework-falsegreen.C5" name="C5 login.robot:7"><failure message="always-true check ...">login.robot:7</failure></testcase></testsuite></testsuites>
```

### Configuration

**Exit codes** (the contract CI relies on):

| Code | Meaning |
|---|---|
| `0` | clean, or only off/baselined findings |
| `10` | low-confidence findings only |
| `20` | at least one high-confidence finding |

Wire exit `20` into CI to block the merge. `10` is a warn band you can choose to fail or not.

**Disable codes:** `--disable C16,C20` turns codes off for this run (comma-separated).

**Diagnostics:** `--diagnostics` reports the opt-in maintainability group as warnings: `D2` (control flow at the test/task level) and `M2` (test/task with too many steps). These are not false-green, the test still verifies, so they are off by default.

**Inline suppression:** a comment on the offending line.

```robotframework
*** Test Cases ***
Polls A Real Service
    Sleep    1s    # falsegreen: ignore[C16]      # silence only C16 on this line
    Should Be Equal    ${result}    ${expected}
```

`# falsegreen: ignore` (no brackets) silences every code on that line; `ignore[C16,C20]` silences only the listed codes. Only the `falsegreen:` token suppresses; a plain `# ignore` does not.

**Severity and confidence filtering:** there is no `--severity` flag and no config file on this scanner. Tune the run with `--disable` and `--diagnostics`, and adopt incrementally with `--baseline`.

**`--config-audit`** is a separate mode: instead of scanning suites it reads the Robot run config (`robot.toml`, `pyproject.toml` `[tool.robot]`, and `*.args` argument files found recursively, skipping ignored directories like `results/`/`output/`) and reports `PL9`, a `--skiponfailure` / `--noncritical` option that turns a failing test into a non-fatal pass (legacy, removed in RF 4+). Run on an argument file carrying `--skiponfailure tag`:

```
run.args
  low  PL9  L1      skip-on-failure / noncritical in the run config turns a failing test into a non-fatal pass (legacy, removed in RF 4+)
           skip-on-failure/noncritical in argument file
           level: project   fix: remove --skiponfailure/--noncritical so a failing test fails the run

0 high, 1 low. https://github.com/vinicq/robotframework-falsegreen
```

The per-file scan cannot see run config, so this mode complements it.

**`--baseline` / `--write-baseline`** adopt the scanner on a suite that already has findings without a wall of red:

```bash
rffalsegreen --write-baseline    # record current findings to .falsegreen-baseline.json
rffalsegreen --baseline          # scan, suppressing everything in the baseline
```

Captured:

```
rffalsegreen: wrote 2 fingerprint(s) to .falsegreen-baseline.json
```

The baseline fingerprints a finding by content, `sha1(relative path, code, test/keyword name, detail)` with no line number, so it survives edits that shift a test up or down the file. Both flags take an optional path (default `.falsegreen-baseline.json`). Commit the baseline so CI sees the same set; a new false-green not in the baseline still fails the run.

### CI integration

**GitHub Actions** (text gate plus SARIF upload to code scanning):

```yaml
name: rffalsegreen
on: [push, pull_request]
jobs:
  scan:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write      # required for the SARIF upload
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.x" }
      - run: pip install robotframework-falsegreen
      - name: Scan and emit SARIF
        run: rffalsegreen tests/ --format sarif --output rffalsegreen.sarif
        continue-on-error: true   # let the upload run even when exit 20
      - uses: github/codeql-action/upload-sarif@v3
        with: { sarif_file: rffalsegreen.sarif }
      - name: Fail on high-confidence findings
        run: rffalsegreen tests/  # exit 20 fails the job
```

**Pre-commit hook** (the repo ships a `.pre-commit-hooks.yaml`):

```yaml
repos:
  - repo: https://github.com/vinicq/robotframework-falsegreen
    rev: v0.6.3          # pin a tag; run `pre-commit autoupdate` to move it
    hooks:
      - id: rffalsegreen
```

Then `pre-commit install`. The hook scopes to `.robot`/`.resource` files and passes the staged paths to the scanner, so it never re-scans `results/`/`output/`. It honors the exit codes, so a high-confidence finding fails the commit. Run it on demand against only the staged files with `pre-commit run rffalsegreen`.

### Scope: what it does NOT do

Static scan: it owns what the keyword structure proves and never runs the suite, so it cannot see runtime-only smells (Test Run War, order dependence across suites). Whether the expected value contradicts intended behaviour is semantic and belongs to the [falsegreen-skill](https://github.com/vinicq/falsegreen-skill) LLM pass. Robot has no standard mutation tester, so the layer "does a green test fail when the code is wrong?" stays manual review. Hygiene lint (long tests, naming, duplication) is [Robocop](https://github.com/MarketSquare/robotframework-robocop) territory, run it alongside. The full code catalog is in the [What it detects](#what-it-detects) table below and the [online docs](https://vinicq.github.io/falsegreen-docs/).

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

### Inline suppression

To silence a single justified finding without disabling the code suite-wide, add a comment on the
offending line. The token and bracket syntax match falsegreen (Python) and falsegreen-js:

```robotframework
*** Test Cases ***
Polls A Real Service
    Sleep    1s    # falsegreen: ignore[C16]      # silence only C16 on this line
    Should Be Equal    ${result}    ${expected}
```

`# falsegreen: ignore` (no brackets) silences every code on that line; `ignore[C16,C20]` silences
only the listed codes. The suppression is scoped to its line, so a sibling test is unaffected, and
only the exact `falsegreen:` token suppresses (a plain `# ignore` does not).

### Baseline (adopt on a suite that already has findings)

To add the scanner to a suite with pre-existing findings without a wall of red, record a baseline and then fail only on new findings:

```bash
rffalsegreen --write-baseline    # record current findings to .falsegreen-baseline.json
rffalsegreen --baseline          # scan, suppressing everything in the baseline
```

Both flags take an optional path (default `.falsegreen-baseline.json`). The baseline fingerprints a finding by content - `sha1(relative path, code, test/keyword name, detail)` with no line number - so it survives edits that shift a test up or down the file. Commit the baseline so CI sees the same set. A new false-green that is not in the baseline still fails the run; shrink the baseline as you fix the recorded ones.

### pre-commit

Run the scanner as a [pre-commit](https://pre-commit.com) hook so a false-green test is caught
before it lands. Add to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/vinicq/robotframework-falsegreen
    rev: v0.6.3
    hooks:
      - id: rffalsegreen
```

The hook scopes to `.robot`/`.resource` files and passes the staged paths to the scanner, so it
never re-scans `results/`/`output/`. It honors the exit codes (`0` clean, `10` low only, `20` high),
so a high-confidence finding fails the commit. To run it on demand against only the staged files
without committing, use `pre-commit run rffalsegreen`.

`--config-audit` is a separate mode: instead of scanning suites, it reads the Robot run config (`robot.toml`, `pyproject.toml` `[tool.robot]`, and `*.args` argument files found recursively, skipping ignored directories like `results/`/`output/`) and reports `PL9` - a `--skiponfailure` / `--noncritical` option that turns a failing test into a non-fatal pass (legacy, removed in RF 4+). The per-file scan cannot see run config.

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
| C9b | low  | RequestsLibrary HTTP method with `expected_status=any`/`anything` — the request accepts every status, so the oracle is disabled (a 500 never fails) |
| C11a | high | self-confirming literal: the expected value is an in-body copy of the actual (`${y}=  Set Variable  ${x}`, then `Should Be Equal  ${x}  ${y}`) — the oracle confirms itself |
| C16 | low  | non-deterministic source: `Sleep`, a clock read (`Get Current Date`), or randomness (`Generate Random String`, `Evaluate` with `datetime`/`random`/`uuid`) |
| C20 | high | verification after a `[Return]`/`Return From Keyword`/`Fail`/`Pass Execution` in the same block — a dead step that never runs |
| C21 | low  | verification only runs conditionally (inside `IF` / `Run Keyword If`) — it may never execute |
| C23 | low  | hard-coded IP-address URL in test data (`http://10.0.0.5:8080`) — environment coupling |
| C32 | low  | skipped test (`robot:skip` / `Skip`) |
| C37 | low  | duplicate data row in a `[Template]` — the same scenario runs twice, no extra coverage |
| C44 | high | library assertion provably true for any value (`Should Contain  ${x}  ${EMPTY}`, `Should Not Be Empty  ${TRUE}`, `Length Should Be` tautology) |
| CC  | low  | commented-out verification keyword (`# Should Be Equal ...`) — the oracle is switched off |
| R1  | high | `Pass Execution` forces the test green regardless of any check |
| R2  | low  | user keyword named like a verifier (`Verify`/`Assert`/`Should`...) but its body verifies nothing — a hollow oracle |
| R3  | high | `*** Test Cases ***` inside a `.resource` file — invalid; the cases never run |
| R4  | high | `No Operation` is the only step — the test/task/keyword does nothing |
| R5  | high | `[Template]` with no data rows — the templated test runs zero cases |
| R6  | low  | `Should Be True` on a string literal (not an expression) — a non-empty string is always truthy, so it never fails |
| R7  | low  | templated test whose in-file `[Template]` keyword contains no verification — every generated case runs without an oracle (only when the keyword resolves in the same file) |
| R8  | high | the only verification lives in `[Setup]`/`Test Setup` — it checks preconditions before the body acts, so the body can break and the suite stays green |
| R8b | low  | the only verification lives in `[Teardown]`/`Test Teardown` — it runs even when the body fails and reports on a separate axis |

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

Measured against the [Open Catalog of Test Smells](https://test-smell-catalog.readthedocs.io/) (517 documented smells), only the false-green slice is in scope. What stays out, on purpose: **brittleness / false-red** (sensitive equality, fragile fixtures - the opposite axis), **hygiene / maintainability** (long tests, magic values - linter territory, Robocop), and **slow, design, naming, duplication, runtime/culture**. The boundary is deliberate: where a smell has a statically provable false-green form, that form is a code here - `Sleep` as synchronization is `C16`, a hard-coded IP URL is `C23`, conditional-only verification is `C21`, and a test with no verification keyword is `C2b`. See [CREDITS.md](CREDITS.md) for the full cross-walk.

### Not implemented, on purpose

Some catalog codes are left out because the gain is not worth the false positives, or because
another tool already owns them. Listing them is part of the scope:

- **RF16 (`Wait Until Keyword Succeeds`)** - a retry wrapper. Legitimate retry around genuinely
  asynchronous behavior is common and idiomatic, so flagging every use would be mostly noise. The
  false-positive rate is too high for a static rule; this is a judgment call left to review.
- **Hygiene already covered by [Robocop](https://github.com/MarketSquare/robotframework-robocop)** —
  RF6 (dead keyword, cross-file), RF8 (unused argument), RF13 (duplicate name), RF14 (missing
  documentation), RF15 (too long), RF19 (unused import). These are maintainability lint, not
  false-green, and Robocop detects them well. Run Robocop alongside this scanner; there is no reason
  to reimplement them.

### C-codes with no idiomatic Robot form

Three Python/JS sibling codes have no clean Robot equivalent and are intentionally skipped:

- **C8 (exact float equality)** - Robot test data is untyped text, so a value cannot be proven to be
  a float from the parse tree (`Should Be Equal As Numbers` even takes a `precision` argument). Any
  rule here would guess, with a high false-positive rate.
- **C18 (compare a stringified value to a literal)** - Robot has no `str()`/`repr()` round-trip
  concept; everything is already a string. There is no structural signal to key on.
- **C48 (dark patch: flip a test-mode flag, then assert)** - Robot has a shape for it
  (`Set Environment Variable    TESTING    true` / `Set Global Variable` then a verification),
  but Robot test data is untyped text: the parse tree cannot prove a variable name is a
  test-mode flag, and a truthy value is just a string. Detecting it would need variable-lifecycle
  tracking with no clean signal, so the false-positive ceiling is too high. Skipped on purpose.

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
