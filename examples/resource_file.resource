# falsegreen-robot examples - a Test Cases section inside a .resource file.
#
# Code: R3
#
# A .resource file holds keywords and variables for reuse; a *** Test Cases ***
# section there is invalid and its cases never run. The CLEAN counterpart is a
# Keywords section, which is exactly what a .resource file is for.

*** Test Cases ***
# --- R3: test cases do not belong in a .resource file ----------------------
R3 Should Not Be Here
    Should Be Equal    ${a}    ${b}


*** Keywords ***
# CLEAN: keywords are the legitimate content of a .resource file.
Do A Thing Clean
    Should Be Equal    ${a}    ${b}
