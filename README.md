# falsegreen-robot

**One problem, one tool: the false positive.** falsegreen-robot finds Robot Framework
tests that pass green without protecting anything - tests that let broken behavior
through because no keyword verifies anything, the failure is swallowed, the check is
always true, or the test is skipped.

Deterministic static scan over the official Robot Framework parser
(`robot.api.get_model`) - no execution. Sibling of
[falsegreen](https://github.com/vinicq/falsegreen) (Python/pytest) and
[falsegreen-js](https://github.com/vinicq/falsegreen-js) (JS/TS). The semantic,
intent-based pass lives in [falsegreen-skill](https://github.com/vinicq/falsegreen-skill).

## Why

A green Robot suite is not proof of correctness. A test case can run keywords and never
call a verification keyword; a `Run Keyword And Ignore Error` can absorb the failure; a
`Should Be True    ${TRUE}` can never fail. This tool flags the patterns a parser can
prove, before they reach review.

## Install

```bash
pip install falsegreen-robot
```

## Usage

```bash
falsegreen-robot                  # scan cwd
falsegreen-robot tests/           # scan a path
falsegreen-robot --json           # machine-readable output
falsegreen-robot --output report.json   # write to a file
falsegreen-robot --output .falsegreen/  # write report.<ext> into a directory
falsegreen-robot --disable C16    # turn off specific codes
```

Each finding is reported with its pyramid level (unit / integration / e2e, read from the suite's imported libraries) and a one-line fix hint, and the summary breaks the findings down by level and lists the most common fixes. `--output` takes a file or a directory: an extension-less or trailing-slash path (e.g. `.falsegreen/`) receives `report.<ext>` for the chosen format. Reports are run artifacts; keep the output directory gitignored.

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
| C3  | high | `Run Keyword And Ignore Error`/`Return Status` swallows the failure, status never asserted |
| C5  | high | always-true (`Should Be True  ${TRUE}`, `Should Be Equal` with equal literals) |
| C6  | low  | weak check — `Should Be True` on a bare variable (truthiness only, not a comparison) |
| C7  | high | self-compare (`Should Be Equal  ${x}  ${x}`) |
| C16 | low  | `Sleep` used as synchronization (timing dependence) |
| C21 | low  | verification only runs conditionally (inside `IF` / `Run Keyword If`) — it may never execute |
| C23 | low  | hard-coded IP-address URL in test data (`http://10.0.0.5:8080`) — environment coupling |
| C32 | low  | skipped test (`robot:skip` / `Skip`) |
| R1  | high | `Pass Execution` forces the test green regardless of any check |
| R2  | low  | user keyword named like a verifier (`Verify`/`Assert`/`Should`...) but its body verifies nothing — a hollow oracle |
| R3  | high | `*** Test Cases ***` inside a `.resource` file — invalid; the cases never run |
| R4  | high | `No Operation` is the only step — the test/task/keyword does nothing |
| R5  | high | `[Template]` with no data rows — the templated test runs zero cases |

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
falsegreen-robot --diagnostics    # include D*/M* as warnings
```

Codes share ids with the sibling scanners where the concept matches (C2/C2b/C3/C5/C7/C16/C21/C32).
A Browser `Get` keyword with no assertion operator is a plain getter, so a test whose only
step is `Get Text  h1` surfaces as no-verification (C2b).

## Test levels (the pyramid)

falsegreen-robot scans Robot suites at every level of the pyramid. Discovery is
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
      <td align="center" valign="top" width="14.28%"><a href="https://vinicq.github.io/md-bridge/"><img src="https://avatars.githubusercontent.com/u/78210890?v=4?s=100" width="100px;" alt="Vinicius Queiroz"/><br /><sub><b>Vinicius Queiroz</b></sub></a><br /><a href="https://github.com/vinicq/falsegreen-robot/commits?author=vinicq" title="Code">💻</a> <a href="https://github.com/vinicq/falsegreen-robot/commits?author=vinicq" title="Documentation">📖</a> <a href="#ideas-vinicq" title="Ideas, Planning, & Feedback">🤔</a> <a href="#maintenance-vinicq" title="Maintenance">🚧</a> <a href="#infra-vinicq" title="Infrastructure (Hosting, Build-Tools, etc)">🚇</a> <a href="https://github.com/vinicq/falsegreen-robot/commits?author=vinicq" title="Tests">⚠️</a> <a href="#research-vinicq" title="Research">🔬</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/homesellerq-coder"><img src="https://avatars.githubusercontent.com/u/294912019?v=4?s=100" width="100px;" alt="Home Seller"/><br /><sub><b>Home Seller</b></sub></a><br /><a href="https://github.com/vinicq/falsegreen-robot/commits?author=homesellerq-coder" title="Code">💻</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->

New contributors are added automatically; the table also recognizes non-code work (docs, ideas, infrastructure, tests, research) via the [all-contributors](https://allcontributors.org) spec.
