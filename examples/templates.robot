# falsegreen-robot examples - duplicate template data row.
#
# Code: C37
#
# The scanner parses the model and never runs these files.

*** Test Cases ***
# --- C37: a [Template] data row repeats an earlier one ---------------------
C37 Same Row Twice
    [Template]    Verify Addition
    1    2    3
    1    2    3
    4    5    9

C37 Distinct Rows Clean
    [Template]    Verify Addition
    1    2    3
    4    5    9
