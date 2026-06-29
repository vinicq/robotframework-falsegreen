# falsegreen-robot examples - execution (the verification exists but never runs,
# or the test runs nothing / is forced green).
#
# Codes: C2, C2b, C3, C20, C21, C32, CC, R1, R4, R5, R7, R8, R8b
#
# BAD cases are flagged; CLEAN look-alikes stay quiet. The scanner parses the
# model and never runs these files (see effectiveness.robot for the layout).

*** Test Cases ***
# --- C2: empty test (no steps) ---------------------------------------------
C2 Empty Test
    [Documentation]    nothing here

C2 Has Steps Clean
    ${r}=    Evaluate    2 + 2
    Should Be Equal As Integers    ${r}    4

# --- C2b: runs keywords but verifies nothing -------------------------------
C2b No Oracle
    Log    hello
    Open Browser    http://x

C2b Verifies Clean
    Log    hello
    Should Be Equal    ${a}    1

# --- C3: swallowed failure (Run Keyword And Ignore Error) ------------------
C3 Swallowed
    Run Keyword And Ignore Error    Do Risky Thing

C3 Status Asserted Clean
    ${status}    ${value}=    Run Keyword And Ignore Error    Do Risky Thing
    Should Be Equal    ${status}    PASS

# --- C20: verification after a Fail never runs -----------------------------
C20 Dead After Fail
    Fail    stop here
    Should Be Equal    ${a}    ${b}

C20 Verify Before Fail Clean
    Should Be Equal    ${a}    ${b}
    Run Keyword If    ${broken}    Fail    reported

# --- C21: verification only inside an IF -----------------------------------
C21 Conditional Only
    Do Something
    IF    ${ready}
        Should Be Equal    ${a}    ${b}
    END

C21 Unconditional Clean
    Should Be Equal    ${a}    ${b}

# --- C32: skipped test never runs ------------------------------------------
C32 Skipped
    [Tags]    robot:skip
    Should Be Equal    ${a}    ${b}

C32 Runs Normally Clean
    [Tags]    smoke
    Should Be Equal    ${a}    ${b}

# --- CC: commented-out verification keyword --------------------------------
CC Oracle Switched Off
    Do Something
    # Should Be Equal    ${a}    ${b}
    Log    moving on

CC Live Oracle Clean
    Do Something
    Should Be Equal    ${a}    ${b}

# --- R1: Pass Execution forces the test green ------------------------------
R1 Forced Green
    Pass Execution    skip the real check
    Should Be Equal    ${a}    ${b}

R1 Honest Verdict Clean
    Do Something
    Should Be Equal    ${a}    ${b}

# --- R4: No Operation is the only step -------------------------------------
R4 Does Nothing
    No Operation

R4 Real Steps Clean
    No Operation
    Should Be Equal    ${a}    ${b}

# --- R5: template with no data rows ----------------------------------------
R5 Templated No Data
    [Template]    Verify Addition

R5 Templated With Data Clean
    [Template]    Verify Addition
    1    2    3
    4    5    9

# --- R7: templated test driven by a hollow in-file template keyword --------
R7 Hollow Template Keyword
    [Template]    Open And Click
    /home    button-1
    /about    button-2

R7 Verifying Template Clean
    [Template]    Verify Sum
    1    2    3
    4    5    9

# --- R8: the only verification is in [Setup] - it checks the wrong phase ----
R8 Verifies In Setup
    [Setup]    Should Be Equal    ${precondition}    ready
    Log    body runs but verifies nothing

R8 Verifies In Body Clean
    [Setup]    Open Application
    Should Be Equal    ${result}    ok

# --- R8b: the only verification is in [Teardown] - a separate axis ----------
R8b Verifies In Teardown
    Do Something
    [Teardown]    Verify Cleanup Succeeded

R8b Verifies In Body Clean
    Should Be Equal    ${result}    ok
    [Teardown]    Close Application


*** Keywords ***
Open And Click
    [Arguments]    ${path}    ${selector}
    Go To    ${path}
    Click    ${selector}

Verify Sum
    [Arguments]    ${a}    ${b}    ${expected}
    ${r}=    Evaluate    ${a} + ${b}
    Should Be Equal As Integers    ${r}    ${expected}
