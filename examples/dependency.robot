# falsegreen-robot examples - dependency (environment coupling / mystery guest).
#
# Code: C23
#
# The scanner parses the model and never runs these files.

*** Test Cases ***
# --- C23: hard-coded IP-address URL ----------------------------------------
C23 Fixed Host IP
    Open Browser    http://10.0.0.5:8080
    Should Be Equal    ${a}    ${b}

C23 Hostname Clean
    Open Browser    http://localhost:8080
    Should Be Equal    ${a}    ${b}
