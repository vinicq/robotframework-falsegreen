# falsegreen-robot examples - effectiveness (no oracle, a trivial oracle, or the
# wrong oracle).
#
# Codes: C5, C6, C7, C9, C44, R6, R2
#
# Each BAD case is one the scanner flags; each CLEAN look-alike, one token away,
# it leaves alone. The scanner parses with robot.api.get_model and never runs
# these files: the keywords they call (Do Risky Thing, ...) need not exist.
# The self-scan is `python -m falsegreen_robot src tests`, so examples/ is not
# scanned by it; tests/test_examples.py scans this file and checks each code.

*** Test Cases ***
# --- C5: always-true check -------------------------------------------------
C5 Always True
    Should Be True    ${TRUE}

C5 Real Condition Clean
    Should Be True    ${count} > 0

# --- C6: weak check (truthiness only) --------------------------------------
C6 Bare Variable
    ${r}=    Get Status
    Should Be True    ${r}

C6 Real Comparison Clean
    Should Be Equal As Integers    ${r}    200

# --- C7: self-compare ------------------------------------------------------
C7 Self Compare
    Should Be Equal    ${value}    ${value}

C7 Distinct Operands Clean
    Should Be Equal    ${actual}    ${expected}

# --- C9: Run Keyword And Expect Error with a catch-all pattern -------------
C9 Catch All Error
    Run Keyword And Expect Error    *    Do Risky Thing

C9 Specific Error Clean
    Run Keyword And Expect Error    ValueError: bad input    Do Risky Thing

# --- C44: library assertion true for any value -----------------------------
C44 Empty Substring
    Should Contain    ${text}    ${EMPTY}

C44 Real Substring Clean
    Should Contain    ${text}    welcome

# --- R6: Should Be True on a string literal (always truthy) -----------------
R6 String Literal
    Should Be True    login succeeded

R6 Expression Clean
    Should Be True    ${count} > 0


*** Keywords ***
# --- R2: a keyword named like a verifier whose body verifies nothing --------
Verify Login Succeeded
    Log    checking login
    Click    id:next

Verify Dashboard Loaded Clean
    Should Be Equal    ${title}    Dashboard
