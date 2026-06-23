# Contributing to robotframework-falsegreen

Thanks for helping. robotframework-falsegreen has one job: flag Robot Framework tests that pass
green without protecting anything. Keep contributions inside that scope.

## Scope

In scope: a test (or task) that can stay green while the behavior is wrong - no
verification keyword, a swallowed `Run Keyword And Ignore Error` or `TRY/EXCEPT`, an
always-true `Should Be True ${TRUE}`, `Pass Execution`, a verification reachable only
through an `IF`. Out of scope: style, naming, length, and convention, unless they make a
passing test unable to fail. Those belong to [Robocop](https://github.com/MarketSquare/robotframework-robocop),
which is complementary, not a competitor. When in doubt, ask: *is there a way for the code
to be wrong and this test to stay green?* If no, it is not a robotframework-falsegreen code.

## Setup

```bash
pip install -e ".[dev]"
pytest -q
ruff check src tests
python -m falsegreen_robot src tests   # self-scan: the tool must not error
```

## Adding a detection code

1. Add the entry to `CASES` in `src/falsegreen_robot/scanner.py` (id, title, confidence,
   judgment J1-J6). Reuse a `C*` id when the smell matches the Python/JS concept; use `R*`
   for Robot-specific patterns; `D*`/`M*` for the opt-in diagnostic/coupling groups.
2. Implement the check over the Robot model (`robot.api.get_model` + `ModelVisitor`). It
   must be provable from the parse tree - no execution.
3. Add a test in `tests/test_scanner.py`: a `.robot` snippet that must flag and a clean
   look-alike that must not.
4. Document it in the README catalog, `docs/guide.md`, and `CHANGELOG.md`.

Precision over recall. `C2b`/`R2` are `low` because a custom keyword can verify without
`Should` in its name. A softened heuristic that misses a case is preferred to one that
flags correct code.

## Recognizing verification keywords

The oracle in Robot is a verification keyword. The scanner recognizes them across libraries
(the `Should` convention plus the Browser assertion engine and RESTinstance schema). If you
add support for a new library, extend `is_verification` and add a test.

## Commit and PR

Small, focused commits. Run pytest + ruff + self-scan before opening the PR. Reference the
issue. Match the surrounding code; keep `robotframework` as the only runtime dependency.
