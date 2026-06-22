"""Tests for falsegreen-robot. Each fixture is a tiny .robot file."""
from falsegreen_robot.scanner import analyze_file, scan, group_of


def codes(tmp_path, body, name="t.robot"):
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    return {x.code for x in analyze_file(str(f))}


def test_clean_test_has_no_findings(tmp_path):
    body = """\
*** Test Cases ***
Adds Two Numbers
    ${r}=    Evaluate    2 + 2
    Should Be Equal As Integers    ${r}    4
"""
    assert codes(tmp_path, body) == set()


def test_c2_empty_test(tmp_path):
    body = """\
*** Test Cases ***
Empty
    [Documentation]    nothing here
"""
    assert "C2" in codes(tmp_path, body)


def test_c2b_no_verification(tmp_path):
    body = """\
*** Test Cases ***
No Oracle
    Log    hello
    Open Browser    http://x
"""
    assert "C2b" in codes(tmp_path, body)


def test_c3_swallowed_failure(tmp_path):
    body = """\
*** Test Cases ***
Swallow
    Run Keyword And Ignore Error    Do Risky Thing
"""
    assert "C3" in codes(tmp_path, body)


def test_c5_always_true(tmp_path):
    body = """\
*** Test Cases ***
Tautology
    Should Be True    ${TRUE}
"""
    assert "C5" in codes(tmp_path, body)


def test_c7_self_compare(tmp_path):
    body = """\
*** Test Cases ***
Self
    Should Be Equal    ${value}    ${value}
"""
    assert "C7" in codes(tmp_path, body)


def test_c16_sleep(tmp_path):
    body = """\
*** Test Cases ***
Sleepy
    Sleep    2s
    Should Be Equal    ${a}    ${b}
"""
    assert "C16" in codes(tmp_path, body)


def test_c32_skip(tmp_path):
    body = """\
*** Test Cases ***
Skipped
    [Tags]    robot:skip
    Should Be Equal    ${a}    ${b}
"""
    assert "C32" in codes(tmp_path, body)


def test_c21_verification_only_inside_if(tmp_path):
    body = """\
*** Test Cases ***
Conditional Check
    Do Something
    IF    ${ready}
        Should Be Equal    ${a}    ${b}
    END
"""
    assert "C21" in codes(tmp_path, body)


def test_c21_run_keyword_if_verification(tmp_path):
    body = """\
*** Test Cases ***
Guarded
    Run Keyword If    ${ready}    Should Be Equal    ${a}    ${b}
"""
    assert "C21" in codes(tmp_path, body)


def test_no_c21_when_an_unconditional_verification_exists(tmp_path):
    body = """\
*** Test Cases ***
Mixed
    Should Be Equal    ${a}    ${b}
    IF    ${ready}
        Should Contain    ${x}    y
    END
"""
    assert "C21" not in codes(tmp_path, body)


def test_r1_pass_execution_forces_green(tmp_path):
    body = """\
*** Test Cases ***
Forced
    Pass Execution    skip the real check
    Should Be Equal    ${a}    ${b}
"""
    assert "R1" in codes(tmp_path, body)


def test_c3_native_try_except_swallows(tmp_path):
    body = """\
*** Test Cases ***
Swallowed
    TRY
        Do Risky Thing
        Should Be Equal    ${a}    ${b}
    EXCEPT    AS    ${e}
        Log    ${e}
    END
"""
    assert "C3" in codes(tmp_path, body)


def test_no_c3_when_except_reraises_with_fail(tmp_path):
    body = """\
*** Test Cases ***
Proper
    TRY
        Do Risky Thing
    EXCEPT    AS    ${e}
        Fail    unexpected: ${e}
    END
    Should Be Equal    ${a}    ${b}
"""
    assert "C3" not in codes(tmp_path, body)


def test_browser_get_without_operator_is_no_verification(tmp_path):
    body = """\
*** Test Cases ***
Getter Only
    Get Text    h1
"""
    assert "C2b" in codes(tmp_path, body)


def test_browser_get_with_operator_is_clean(tmp_path):
    body = """\
*** Test Cases ***
Browser Assert
    Get Text    h1    ==    Welcome
"""
    assert codes(tmp_path, body) == set()


def test_rpa_task_is_scanned(tmp_path):
    body = """\
*** Tasks ***
Process Invoice
    Open Application
    Read Invoice Data
"""
    assert "C2b" in codes(tmp_path, body)  # tasks (RPA) are analyzed like test cases


def test_d2_control_flow_diagnostic(tmp_path):
    body = """\
*** Test Cases ***
Has Logic
    Should Be Equal    ${a}    ${b}
    IF    ${cond}
        Log    branch
    END
"""
    assert "D2" in codes(tmp_path, body)


def test_m2_long_task(tmp_path):
    steps = "\n".join("    Log    step %d" % i for i in range(12))
    body = "*** Test Cases ***\nLong\n%s\n    Should Be Equal    ${a}    ${b}\n" % steps
    assert "M2" in codes(tmp_path, body)


def test_groups_by_prefix(tmp_path):
    assert group_of("C2") == "false-positive"
    assert group_of("R1") == "false-positive"
    assert group_of("D2") == "diagnostic"
    assert group_of("M2") == "coupling"


def test_scan_hides_diagnostics_by_default(tmp_path):
    body = """\
*** Test Cases ***
Has Logic
    Should Be Equal    ${a}    ${b}
    IF    ${cond}
        Log    x
    END
"""
    f = tmp_path / "s.robot"
    f.write_text(body, encoding="utf-8")
    off = {x.code for x in scan([str(f)])}
    on = {x.code for x in scan([str(f)], diagnostics=True)}
    assert "D2" not in off          # diagnostic group off by default
    assert "D2" in on               # surfaced with --diagnostics


def test_custom_verify_keyword_counts_as_oracle(tmp_path):
    body = """\
*** Test Cases ***
Delegates
    Do Login
    Verify Dashboard Loaded
"""
    assert "C2b" not in codes(tmp_path, body)
