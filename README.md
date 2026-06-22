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
falsegreen-robot --disable C16    # turn off specific codes
```

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
| C2  | high | empty test case (no keywords run) |
| C2b | low  | runs keywords but no verification keyword (no oracle) |
| C3  | high | `Run Keyword And Ignore Error`/`Return Status` swallows the failure, status never asserted |
| C5  | high | always-true (`Should Be True  ${TRUE}`, `Should Be Equal` with equal literals) |
| C7  | high | self-compare (`Should Be Equal  ${x}  ${x}`) |
| C16 | low  | `Sleep` used as synchronization (timing dependence) |
| C21 | low  | verification only runs conditionally (inside `IF` / `Run Keyword If`) — it may never execute |
| C32 | low  | skipped test (`robot:skip` / `Skip`) |

Codes share ids with the sibling scanners where the concept matches (C2/C2b/C3/C5/C7/C16/C32).
A Browser `Get` keyword with no assertion operator is a plain getter, so a test whose only
step is `Get Text  h1` surfaces as no-verification (C2b).

## Scope and honesty

Static scan: it owns what the keyword structure proves. It does not run the suite, so it
cannot see runtime-only smells (Test Run War, order dependence across suites). Whether the
expected value contradicts the intended behavior is semantic and belongs to
`falsegreen-skill`. Precision over recall: `C2b` is low-confidence because a custom keyword
may assert internally without `Should` in its name.

## License

MIT, Vinicius Queiroz.
