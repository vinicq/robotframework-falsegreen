# falsegreen-robot examples - diagnostic / coupling group (OFF by default).
#
# Codes: D2 (control flow at the test level), M2 (too many steps)
#
# These are NOT false-green: the test still verifies something. They flag what
# the Robot style guide advises against (no IF/FOR at the test-case level, keep
# tests short), so they are off by default and surface only with --diagnostics.
# A plain scan reports none of these; the CLEAN look-alikes stay quiet even when
# the group is enabled. The scanner parses the model and never runs these files.

*** Test Cases ***
# --- D2: control flow at the test/task level -------------------------------
D2 Has Logic
    Should Be Equal    ${a}    ${b}
    IF    ${cond}
        Log    branch
    END

D2 Flat Clean
    Should Be Equal    ${a}    ${b}

# --- M2: too many steps (the guide suggests max ~10) -----------------------
M2 Long Test
    Log    step 1
    Log    step 2
    Log    step 3
    Log    step 4
    Log    step 5
    Log    step 6
    Log    step 7
    Log    step 8
    Log    step 9
    Log    step 10
    Log    step 11
    Should Be Equal    ${a}    ${b}

M2 Short Clean
    Do One Thing
    Should Be Equal    ${a}    ${b}
