# robotframework-falsegreen guide

One question per test: **is there a way for the behavior to be wrong and this test to stay
green?** If yes, the test is not protecting what it claims. This guide explains each code
with a flagged example and a clean look-alike. The scanner reads the Robot Framework parse
tree only (`robot.api.get_model`); it never runs the suite.

The oracle in Robot is the **verification keyword**. The scanner recognizes it across
libraries: the `Should` convention (`Should Be Equal`, `Element Should Be Visible`), the
Browser assertion engine (`Get Text  sel  ==  expected`), RESTinstance schema keywords,
and custom `Verify*`/`Assert*`/`Validate*` keywords. A test with none of them verifies
nothing.

Confidence: **high** blocks (exit 20), **low** warns (exit 10). Judgments J1-J6 are shared
with [falsegreen-skill](https://github.com/vinicq/falsegreen-skill):
J1 does the verification run? · J2 is the oracle independent? · J4 enough, and the right
thing? · J5 coupled / hard to maintain?

---

## C2 — empty test case (high, J1)

```robotframework
*** Test Cases ***
Creates A User
    [Documentation]    nothing runs here
```
Clean: a body with keywords and a verification keyword.

## C2b — runs keywords but verifies nothing (low, J1)

```robotframework
*** Test Cases ***
Saves
    Open Browser    http://x
    Log    saved
```
No oracle. Clean: end with `Should Be Equal    ${status}    ok`, or any recognized
verification keyword. Low confidence because a custom keyword may assert internally without
`Should` in its name (see R2 for the case where it does not).

## C3 — the failure is swallowed (high, J1)

```robotframework
*** Test Cases ***
Swallow
    Run Keyword And Ignore Error    Do Risky Thing
```
`Run Keyword And Ignore Error` and `Run Keyword And Return Status` absorb the failure; if
the returned status is never asserted, a broken step stays green. This covers two forms: the
result discarded entirely (the call above, no assignment), and the status captured in a
variable that no later step reads (`${status}    ${value}=    Run Keyword And Ignore Error
...` with no use of `${status}` or `${value}` afterward). The same applies to a native
`TRY/EXCEPT` that catches the error and only logs it.

Clean: assert the captured status, or let `EXCEPT` re-raise with `Fail`.

```robotframework
*** Test Cases ***
Proper
    ${status}    ${msg}=    Run Keyword And Ignore Error    Do Risky Thing
    Should Be Equal    ${status}    PASS
```

## C5 — always-true check (high, J2)

```robotframework
*** Test Cases ***
Tautology
    Should Be True    ${TRUE}
```
A constant condition, or `Should Be Equal` with two equal literals, can never fail. Clean:
`Should Be True    ${count} > 0`.

## C6 — weak truthiness check (low, J4)

```robotframework
*** Test Cases ***
Weak Check
    ${r}=    Get Status
    Should Be True    ${r}
```
`Should Be True` on a bare variable checks only that it is truthy, not that it holds the
expected value. Clean: a real comparison, `Should Be True    ${r} == 200`.

## C7 — compares a thing to itself (high, J2)

```robotframework
*** Test Cases ***
Self
    Should Be Equal    ${value}    ${value}
```
A tautology. Clean: `Should Be Equal    ${value}    expected`.

## C16 — Sleep used as synchronization (low, J1)

```robotframework
*** Test Cases ***
Sleepy
    Sleep    2s
    Should Be Equal    ${a}    ${b}
```
A fixed `Sleep` makes the result depend on timing; the test passes or fails by luck on a
slow machine. Clean: a `Wait Until ...` keyword that fails on timeout.

## C21 — verification only runs conditionally (low, J1)

```robotframework
*** Test Cases ***
Conditional Check
    Do Something
    IF    ${ready}
        Should Be Equal    ${a}    ${b}
    END
```
The only check sits inside an `IF` (or a `Run Keyword If`), so it may never execute. Clean:
at least one verification keyword runs unconditionally.

## C32 — skipped test (low, J1)

```robotframework
*** Test Cases ***
Skipped
    [Tags]    robot:skip
    Should Be Equal    ${a}    ${b}
```
Also a `Skip` keyword in the body. A skipped test reports green without running.

## R1 — Pass Execution forces green (high, J1)

```robotframework
*** Test Cases ***
Forced
    Pass Execution    skip the real check
    Should Be Equal    ${a}    ${b}
```
`Pass Execution` ends the test as passed; the verification after it never matters. Clean:
remove it, or guard it on a documented, intentional condition.

## R2 — a verifier keyword that verifies nothing (low, J1)

```robotframework
*** Keywords ***
Verify Login Succeeded
    Log    checking login
    Click    id:next
```
The keyword is named like an oracle (`Verify`/`Assert`/`Validate`/`Should`...) but its body
has no verification keyword. A test that calls `Verify Login Succeeded` looks protected and
is not. This is the root cause of a missed C2b: the test delegates to a hollow verifier.

Clean: the keyword asserts something, `Should Be Equal    ${status}    ok`. An action
keyword (`Open The Application`) is not flagged: only verifier-named keywords are.

## R3 — Test Cases inside a .resource file (high, J1)

```robotframework
# orders.resource
*** Test Cases ***
Should Not Be Here
    Should Be Equal    ${a}    ${b}
```
A `.resource` file exists to share keywords and variables. A `*** Test Cases ***` section
there is invalid and never runs. Move the cases to a `.robot` suite. The keywords in the
file are still analyzed.

## R4 — No Operation is the only step (high, J1)

```robotframework
*** Test Cases ***
Does Nothing
    No Operation
```
`No Operation` is a placeholder that does nothing. As the only step, the test runs green
without exercising anything. Also flagged in a keyword whose only step is `No Operation`.

## R5 — empty [Template] (high, J1)

```robotframework
*** Test Cases ***
Templated No Data
    [Template]    Verify Addition
```
A templated test is driven by its data rows. With no rows, Robot generates zero cases and
the test never runs. Add data rows under the `[Template]`, or remove it.

## C2 (keywords) — empty keyword (high, J1)

```robotframework
*** Keywords ***
Validate Order
    [Documentation]    not implemented yet
```
A keyword with only settings and no steps does nothing. Called where verification belongs,
it leaves the test green for free. Implement it or remove it.

## C23 — hard-coded IP-address URL (low, J6)

```robotframework
*** Test Cases ***
Hits A Fixed Host
    Open Browser    http://10.0.0.5:8080
    Page Should Contain    Welcome
```
A literal IP address ties the test to one machine: it passes or fails on whether that host
is up, not on the behavior. A hostname URL (`http://localhost:8080`) is not flagged - it is
too common in E2E to be a reliable signal. Clean: read the target from a variable or
environment.

## C9 — expects any error (low, J4)

```robotframework
*** Test Cases ***
Accepts Any Error
    Run Keyword And Expect Error    *    Do Risky Thing
```
A catch-all pattern (`*`, `GLOB:*`, `EQUALS:*`) passes on any error - a typo that raises the
wrong failure still goes green. Clean: match the specific message or pattern
(`Run Keyword And Expect Error    ValueError: *    Do Risky Thing`).

## C20 — verification after a terminator (high, J1)

```robotframework
*** Keywords ***
Returns Early
    Do Something
    [Return]    ${x}
    Should Be Equal    ${a}    ${b}
```
Nothing after a `[Return]`/`Return From Keyword` (in a keyword) or a `Fail`/`Pass Execution`
(in a test) in the same block runs. A verification there is dead code. Clean: move the check
before the terminator so it executes.

## C37 — duplicate [Template] data row (low, J4)

```robotframework
*** Test Cases ***
Same Row Twice
    [Template]    Verify Addition
    1    2    3
    1    2    3
```
A repeated row drives the templated keyword with the same inputs twice - the second run adds
no coverage and hides a real case the author may have meant to write. Clean: remove the
duplicate, or replace it with the case that was intended.

## CC — commented-out verification keyword (low, J1)

```robotframework
*** Test Cases ***
Oracle Switched Off
    Do Something
    # Should Be Equal    ${a}    ${b}
```
A verification keyword left in a comment is an oracle that no longer runs. The line reads as
if the test still checks something; it does not. Clean: restore the keyword, or delete the
line. A plain prose comment (`# this should be revisited`) is not flagged - the rule keys on
a capitalized verification keyword (`Should`/`Verify`/`Assert`/`Validate`).

## R6 — Should Be True on a string literal (low, J4)

```robotframework
*** Test Cases ***
Vacuous Check
    Should Be True    login succeeded
```
`Should Be True` evaluates its argument as a Python expression. A bare non-empty string is
always truthy, so the check can never fail. Clean: pass a real expression
(`Should Be True    ${count} > 0`). A bare `${x}` is the weaker C6 (truthiness); `${TRUE}` /
`1` is the constant C5.

## R7 — templated test driven by a hollow in-file keyword (low, J1)

```robotframework
*** Test Cases ***
Navigates Each Page
    [Template]    Open And Click
    /home     button-1
    /about    button-2

*** Keywords ***
Open And Click
    [Arguments]    ${path}    ${selector}
    Go To    ${path}
    Click    ${selector}
```
A templated test runs its `[Template]` keyword once per data row. When that keyword is defined
in the same file and its body never verifies anything, every generated case passes without an
oracle. Clean: the template keyword asserts the outcome.

```robotframework
*** Test Cases ***
Checks Each Sum
    [Template]    Verify Sum
    1    2    3
    4    5    9

*** Keywords ***
Verify Sum
    [Arguments]    ${a}    ${b}    ${expected}
    ${r}=    Evaluate    ${a} + ${b}
    Should Be Equal As Integers    ${r}    ${expected}
```
The rule only fires when the keyword resolves in the same file. A `[Template]` keyword imported
from a resource is left alone - it may verify through a keyword the scanner cannot see. A
hollow keyword named like a verifier (`Verify Page`) is already flagged R2 on its definition,
so the templated test is not double-flagged.

---

## Opt-in groups (default off, `--diagnostics`)

These are not false-green. The test still verifies, so they stay off by default. Three
groups mirror the sibling scanners: `false-positive` (C*/R*, on), `diagnostic` (D*, opt-in),
`coupling` (M*, opt-in).

### D2 — control flow at the test level (diagnostic, J4)

```robotframework
*** Test Cases ***
Has Logic
    Should Be Equal    ${a}    ${b}
    IF    ${cond}
        Log    branch
    END
```
`IF`/`FOR`/`WHILE`/`TRY` directly in a test case makes the path data-dependent and harder
to read. The Robot Framework guide advises pushing logic into keywords.

### M2 — too many steps (coupling, J5)

A test or task with more steps than the threshold (default ~10) is doing too much. Splitting
it makes each test fail for one reason.

---

## Out of scope

Style, naming, and convention belong to
[Robocop](https://github.com/MarketSquare/robotframework-robocop), which is complementary.
Runtime-only smells (order dependence across suites, a Test Run War) need execution and are
not visible to a static parse. Whether the expected value contradicts the intended behavior
is semantic and belongs to
[falsegreen-skill](https://github.com/vinicq/falsegreen-skill), the LLM pass.
