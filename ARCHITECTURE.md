# Architecture

robotframework-falsegreen is a deterministic static scanner for Robot Framework tests. It reads
`.robot` and `.resource` files, parses them with the official Robot Framework parser, and
flags the patterns that let a test pass green without protecting anything. It never imports
keyword libraries, starts a browser, or runs the suite.

## The pipeline

```
paths ──▶ discover ──▶ get_model ──▶ ModelVisitor ──▶ findings ──▶ report / exit code
```

1. **Discover.** Walk the paths. A file counts when its extension is `.robot` or
   `.resource`; build and vendor directories are skipped.
2. **Parse.** `robot.api.get_model` builds the same parse tree Robot itself uses. Using the
   official parser, not a regex, means the scanner reads the file the way the runner does:
   sections, settings, control structures, RPA tasks. No keyword is imported and nothing
   executes.
3. **Visit.** A `robot.parsing.ModelVisitor` subclass walks the tree. `visit_TestCase`,
   `visit_Task` (RPA), and `visit_Keyword` apply the case catalog. The shared call-level
   checks (always-true, self-compare, `Sleep`, weak truthiness) run over every keyword call;
   the structural checks (empty, no-oracle, swallowed failure, conditional-only
   verification, forced green) run per test or task.
4. **Report.** Readable text or JSON (`--json`). The exit code is the CI contract.

## Why Robot needs its own scanner

Robot Framework is a keyword DSL, not Python source, so the `ast` module that powers
[falsegreen](https://github.com/vinicq/falsegreen) cannot read it. The correct parse comes
from `robot.api.get_model`, which is why this is a separate repository that depends on
`robotframework`, rather than a module inside the zero-dependency Python scanner.

## The oracle problem

In pytest the oracle is `assert`; in Jest it is `expect`. In Robot there is no single
keyword. Verification is spread across libraries. The scanner recognizes the oracle by
convention and by library form, in `is_verification`:

- the **`Should`** convention (`Should Be Equal`, `Element Should Be Visible`) - BuiltIn,
  Collections, String, SeleniumLibrary, and most others;
- the **Browser** assertion engine, where the operator carries the assertion
  (`Get Text  sel  ==  expected`);
- **RESTinstance** schema keywords;
- custom **`Verify*`/`Assert*`/`Validate*`** keywords, and `Wait Until ...` keywords that
  fail on timeout.

A test with none of these verifies nothing (C2b). The convention is documented; a custom
keyword that asserts without `Should` in its name is the reason C2b is low-confidence, and
the reason R2 exists: a keyword named like a verifier whose body asserts nothing is a hollow
oracle.

## Output contract

| Exit | Meaning |
|------|---------|
| `0`  | clean |
| `10` | low-confidence findings only |
| `20` | at least one high-confidence finding |

Each finding carries code, confidence (`high`/`low`), file, line, and judgment (J1-J6).
`--disable C16` turns off specific codes. Groups split by prefix: `false-positive` (C*/R*,
on), `diagnostic` (D*, opt-in via `--diagnostics`), `coupling` (M*, opt-in).

## The boundary: static, semantic, runtime

The scanner owns what the keyword structure proves. Outside that line:

- **Semantic** (the expected value contradicts the intended behavior) belongs to
  [falsegreen-skill](https://github.com/vinicq/falsegreen-skill), the LLM pass.
- **Runtime** (a Test Run War, order dependence across suites) needs execution, which the
  scanner does not do.
- **Style and naming** belong to [Robocop](https://github.com/MarketSquare/robotframework-robocop),
  which is complementary, not a competitor.

Precision over recall: `C2b`/`R2` are low-confidence because a custom keyword can verify
without `Should` in its name. A softened heuristic that misses a case beats one that flags
correct code.

## Siblings

[falsegreen](https://github.com/vinicq/falsegreen) (Python, `ast`) and
[falsegreen-js](https://github.com/vinicq/falsegreen-js) (JS/TS, TypeScript compiler API).
Codes share an id across the family where the smell is the same concept (C2, C2b, C3, C5,
C7, C16, C21, C32).
