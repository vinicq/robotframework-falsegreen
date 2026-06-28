# robotframework-falsegreen examples

Worked samples for every code the scanner emits. Each code has a **BAD** case
the scanner flags and a **CLEAN** look-alike, one token away, it leaves alone -
so you can see both the smell and the legitimate pattern it must not be confused
with.

These are scan targets, not a runnable suite. The keywords they call (`Do Risky
Thing`, `Verify Addition`, ...) need not exist: the scanner parses the file with
`robot.api.get_model` and never executes it. The self-scan
(`python -m falsegreen_robot src tests`) does not include `examples/`, so it
stays out of the tool's check on itself. `tests/test_examples.py` scans each
file and asserts every code below fires in its file.

## Layout

| File | Theme | Codes |
|---|---|---|
| `effectiveness.robot` | no oracle / trivial oracle / wrong oracle | C5, C6, C7, C9, C44, R6, R2 |
| `execution.robot` | the verification never runs, or the test is forced green | C2, C2b, C3, C20, C21, C32, CC, R1, R4, R5, R7 |
| `nondeterminism.robot` | passes or fails by luck (Sleep, clock, randomness) | C16 |
| `dependency.robot` | environment coupling / mystery guest | C23 |
| `templates.robot` | duplicate template data row | C37 |
| `resource_file.resource` | test cases in a `.resource` file | R3 |
| `diagnostics.robot` | maintainability (opt-in, off by default) | D2, M2 |

`R3` needs a `.resource` file (its smell is a test-case section in the wrong
file kind). `R2`/`R7` need a `*** Keywords ***` section, so they live alongside
the test cases that use them.

## Run the scanner on the examples

```bash
python -m falsegreen_robot examples
```

The BAD cases are reported; the `... Clean` look-alikes are not. The diagnostic
group (D2/M2) is off by default; surface it with `--diagnostics`:

```bash
python -m falsegreen_robot examples --diagnostics
```

## Codes with no example here

`PL9` is the project layer: it audits the Robot run config (`--config-audit`,
e.g. a `--skiponfailure` in an `*.args` file or `skip-on-failure` in
`robot.toml`), not any one `.robot` file, so it has no test-file example.
