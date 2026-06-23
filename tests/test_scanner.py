"""Tests for robotframework-falsegreen. Each fixture is a tiny .robot file."""
import json

from falsegreen_robot.scanner import (
    analyze_file, scan, group_of, main, resolve_output_path,
    _render_text, CASES, FIX_HINTS,
)


def codes(tmp_path, body, name="t.robot"):
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    return {x.code for x in analyze_file(str(f))}


def _findings(tmp_path, body, name="t.robot"):
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    return analyze_file(str(f))


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


def test_c6_should_be_true_on_bare_variable(tmp_path):
    body = """\
*** Test Cases ***
Weak Check
    ${r}=    Get Status
    Should Be True    ${r}
"""
    assert "C6" in codes(tmp_path, body)


def test_no_c6_when_should_be_true_has_comparison(tmp_path):
    body = """\
*** Test Cases ***
Real Check
    Should Be True    ${count} > 0
"""
    assert "C6" not in codes(tmp_path, body)


def test_r2_hollow_verifier_keyword(tmp_path):
    body = """\
*** Keywords ***
Verify Login Succeeded
    Log    checking login
    Click    id:next
"""
    assert "R2" in codes(tmp_path, body)


def test_no_r2_when_verifier_keyword_asserts(tmp_path):
    body = """\
*** Keywords ***
Verify Login Succeeded
    Should Be Equal    ${status}    ok
"""
    assert "R2" not in codes(tmp_path, body)


def test_action_keyword_not_flagged_as_r2(tmp_path):
    body = """\
*** Keywords ***
Open The Application
    Log    opening
    Click    id:start
"""
    assert "R2" not in codes(tmp_path, body)


def test_c5_inside_user_keyword(tmp_path):
    body = """\
*** Keywords ***
Check Result
    Should Be True    ${TRUE}
"""
    assert "C5" in codes(tmp_path, body)


def test_resource_file_is_scanned(tmp_path):
    body = """\
*** Keywords ***
Validate Order
    Log    pretending to validate
"""
    assert "R2" in codes(tmp_path, body, name="keywords.resource")


def test_custom_verify_keyword_counts_as_oracle(tmp_path):
    body = """\
*** Test Cases ***
Delegates
    Do Login
    Verify Dashboard Loaded
"""
    assert "C2b" not in codes(tmp_path, body)


# --- R3/R4/R5, empty keyword, C23: codes from the consolidated catalog ------

def test_r3_test_cases_in_resource_file(tmp_path):
    body = """\
*** Test Cases ***
Should Not Be Here
    Should Be Equal    ${a}    ${b}
"""
    assert "R3" in codes(tmp_path, body, name="keywords.resource")


def test_no_r3_for_keywords_in_resource(tmp_path):
    body = """\
*** Keywords ***
Do A Thing
    Should Be Equal    ${a}    ${b}
"""
    assert "R3" not in codes(tmp_path, body, name="keywords.resource")


def test_r4_no_operation_only_step(tmp_path):
    body = """\
*** Test Cases ***
Does Nothing
    No Operation
"""
    assert "R4" in codes(tmp_path, body)


def test_no_r4_when_real_steps_exist(tmp_path):
    body = """\
*** Test Cases ***
Real
    No Operation
    Should Be Equal    ${a}    ${b}
"""
    assert "R4" not in codes(tmp_path, body)


def test_r5_template_without_data_rows(tmp_path):
    body = """\
*** Test Cases ***
Templated No Data
    [Template]    Verify Addition
"""
    assert "R5" in codes(tmp_path, body)


def test_no_r5_when_template_has_data(tmp_path):
    body = """\
*** Test Cases ***
Templated With Data
    [Template]    Verify Addition
    1    2    3
    4    5    9
"""
    assert "R5" not in codes(tmp_path, body)


def test_c2_empty_keyword(tmp_path):
    body = """\
*** Keywords ***
Placeholder
    [Documentation]    not implemented yet
"""
    assert "C2" in codes(tmp_path, body, name="kw.resource")


def test_no_c2_for_keyword_with_steps(tmp_path):
    body = """\
*** Keywords ***
Real Keyword
    Should Be Equal    ${a}    ${b}
"""
    assert "C2" not in codes(tmp_path, body, name="kw.resource")


def test_c23_hardcoded_ip_url(tmp_path):
    body = """\
*** Test Cases ***
Hits A Fixed Host
    Open Browser    http://10.0.0.5:8080
    Should Be Equal    ${a}    ${b}
"""
    assert "C23" in codes(tmp_path, body)


def test_no_c23_for_hostname_url(tmp_path):
    body = """\
*** Test Cases ***
Hits A Hostname
    Open Browser    http://localhost:8080
    Should Be Equal    ${a}    ${b}
"""
    assert "C23" not in codes(tmp_path, body)


# --- Codex review fixes ------------------------------------------------------

def test_c23_ip_url_inside_assertion_args(tmp_path):
    body = """\
*** Test Cases ***
Asserts Against A Fixed Host
    Should Be Equal    ${url}    http://10.0.0.5:8080
"""
    assert "C23" in codes(tmp_path, body)


def test_c2b_populated_template_with_non_verifying_keyword(tmp_path):
    body = """\
*** Test Cases ***
Logs Each Row
    [Template]    Log
    first
    second
"""
    assert "C2b" in codes(tmp_path, body)


def test_no_c2b_populated_template_with_verifying_keyword(tmp_path):
    body = """\
*** Test Cases ***
Verifies Each Row
    [Template]    Verify Addition
    1    2    3
    4    5    9
"""
    assert "C2b" not in codes(tmp_path, body)


# --- status report: pyramid level, fix-hint, output dir ----------------------

_EMPTY_TEST = "*** Test Cases ***\nEmpty\n    [Documentation]    nothing\n"


def test_level_unit_by_default(tmp_path):
    fs = _findings(tmp_path, _EMPTY_TEST)
    assert fs and all(f.level == "unit" for f in fs)


def test_level_integration_on_requests_library(tmp_path):
    body = "*** Settings ***\nLibrary    RequestsLibrary\n" + _EMPTY_TEST
    fs = _findings(tmp_path, body)
    assert fs and all(f.level == "integration" for f in fs)


def test_level_integration_on_database_library(tmp_path):
    body = "*** Settings ***\nLibrary    DatabaseLibrary\n" + _EMPTY_TEST
    fs = _findings(tmp_path, body)
    assert fs and all(f.level == "integration" for f in fs)


def test_level_e2e_on_selenium_library(tmp_path):
    body = "*** Settings ***\nLibrary    SeleniumLibrary\n" + _EMPTY_TEST
    fs = _findings(tmp_path, body)
    assert fs and all(f.level == "e2e" for f in fs)


def test_level_e2e_wins_over_integration(tmp_path):
    body = ("*** Settings ***\nLibrary    RequestsLibrary\nLibrary    Browser\n"
            + _EMPTY_TEST)
    fs = _findings(tmp_path, body)
    assert fs and all(f.level == "e2e" for f in fs)


def test_finding_dict_carries_level_and_fix(tmp_path):
    fs = _findings(tmp_path, _EMPTY_TEST)
    d = fs[0].dict()
    assert d["code"] == "C2"
    assert d["level"] == "unit"
    assert d["fix"] == FIX_HINTS["C2"]  # the exact remediation, not just truthiness


def test_render_text_shows_level_and_fix_and_summary(tmp_path):
    fs = _findings(tmp_path, _EMPTY_TEST)
    out = _render_text(fs)
    assert "level: unit" in out
    assert "fix:" in out
    assert "By level: unit:" in out
    assert "Top fixes:" in out


def test_fix_hints_cover_every_case():
    missing = [c for c in CASES if c not in FIX_HINTS]
    assert missing == []


def test_output_directory_writes_report_file(tmp_path):
    f = tmp_path / "t.robot"
    f.write_text(_EMPTY_TEST, encoding="utf-8")
    outdir = tmp_path / ".falsegreen"
    main([str(f), "--json", "--output", str(outdir)])
    report = outdir / "report.json"
    assert report.exists()
    doc = json.loads(report.read_text(encoding="utf-8"))
    assert doc["findings"][0]["code"] == "C2"


def test_output_file_path_writes_single_file(tmp_path):
    f = tmp_path / "t.robot"
    f.write_text(_EMPTY_TEST, encoding="utf-8")
    out = tmp_path / "sub" / "report.txt"
    main([str(f), "--output", str(out)])
    assert out.is_file()


def test_resolve_output_path_dir_vs_file(tmp_path):
    d = resolve_output_path(str(tmp_path / ".falsegreen"), "json")
    assert d.endswith("report.json")
    fpath = resolve_output_path(str(tmp_path / "r.txt"), "text")
    assert fpath.endswith("r.txt")
