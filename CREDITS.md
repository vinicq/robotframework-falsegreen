# References

falsegreen-robot detects false-green test smells in Robot Framework. Its catalog draws on
the academic test-smell literature, on the Robot Framework documentation that defines what
a verification keyword is, and on the existing Robot linter. This file credits those
sources and maps each to the codes it informs.

## Founding and conceptual

- **van Deursen, Moonen, van den Bergh, Kok (2001).** "Refactoring Test Code." XP 2001.
  The original catalog of 11 test smells. Source of the general vocabulary that the
  sibling scanners share.
- **Delplanque, Ducasse, Polito, Black, Etien (2019).** "Rotten Green Tests." ICSE 2019.
  Green tests whose assertions never execute. The conceptual origin of the "false-green"
  framing and of the codes where a check is present but cannot run: C21 (verification
  guarded by `IF`) and R2 (a verifier keyword whose body asserts nothing). Cross-language
  extension: EMSE 2021.

## Robot Framework specific

- **Robot Framework User Guide** (robotframework.org). Defines the test/task/keyword
  structure the scanner walks, the `*** Tasks ***` section for RPA, `.resource` files, and
  control structures (`IF`, `TRY/EXCEPT`, `FOR`, `WHILE`). Source for what D2 treats as
  test-level control flow.
- **BuiltIn library (libdoc).** The `Should` naming convention for verification keywords
  (`Should Be Equal`, `Should Be True`, `Should Contain`), plus `Pass Execution`,
  `Run Keyword And Ignore Error`, `Run Keyword And Return Status`, and `Skip`. This is the
  authoritative basis for the oracle vocabulary in `is_verification` and for C3, C5, C7,
  R1, and C32.
- **Library assertion forms beyond `Should`.** SeleniumLibrary (`Element Should Be
  Visible`, `Wait Until ... Visible`), the Browser library assertion engine
  (`Get Text  sel  ==  expected`), RESTinstance schema keywords, and DatabaseLibrary
  (`Row Count Should Be Equal`). These define the cross-library oracle set so C2b does not
  fire on a test that verifies through a non-`Should` keyword.

## Tooling baseline

- **Robocop** (MarketSquare/robotframework-robocop). The Robot Framework linter for style,
  naming, and convention. Complementary, not a competitor: Robocop checks how the code
  reads; falsegreen-robot checks whether a passing test can still fail. The boundary
  between the two is the scope line in CONTRIBUTING.

## Code-to-source map

| Code | Primary source(s) |
|---|---|
| C2, C2b | van Deursen 2001 (Empty/Unknown Test); BuiltIn oracle vocabulary |
| C3 | BuiltIn `Run Keyword And Ignore Error` / `Return Status`; native `TRY/EXCEPT` |
| C5, C7 | Redundant/always-true assertion (van Deursen 2001; BuiltIn) |
| C6 | weak truthiness check on a bare variable (BuiltIn `Should Be True`) |
| C16 | Sleepy Test (van Deursen 2001) applied to BuiltIn `Sleep` |
| C21, R2 | Rotten Green Tests (Delplanque 2019): assertion present but unreachable or hollow |
| C32 | BuiltIn `Skip` / `robot:skip` tag |
| R1 | BuiltIn `Pass Execution` (forced green) |
| D2 | test-level control flow (Robot Framework User Guide) |
| M2 | long test / too many steps (style guidance) |

Detailed per-source notes and the running research live in a separate private study.
