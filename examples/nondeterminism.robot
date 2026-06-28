# falsegreen-robot examples - nondeterminism (passes or fails by luck: a wait,
# a clock read, or randomness).
#
# Code: C16
#
# The scanner parses the model and never runs these files.

*** Test Cases ***
# --- C16: Sleep used as a wait ---------------------------------------------
C16 Sleep
    Sleep    2s
    Should Be Equal    ${a}    ${b}

C16 Wait Until Clean
    Wait Until Element Is Visible    id:result
    Should Be Equal    ${a}    ${b}

# --- C16: a clock read -----------------------------------------------------
C16 Reads The Clock
    ${d}=    Get Current Date
    Should Be Equal    ${d}    ${expected}

C16 Fixed Date Clean
    ${d}=    Convert Date    2026-01-01    result_format=%Y
    Should Be Equal    ${d}    2026

# --- C16: randomness -------------------------------------------------------
C16 Random String
    ${s}=    Generate Random String
    Should Not Be Empty    ${s}

C16 Deterministic Clean
    ${s}=    Evaluate    "abc".upper()
    Should Be Equal    ${s}    ABC
