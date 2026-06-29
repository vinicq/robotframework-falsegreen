"""Tests for robotframework-falsegreen. Each fixture is a tiny .robot file."""
import pytest
import json

from falsegreen_robot.scanner import (
    analyze_file, scan, group_of, main, resolve_output_path,
    _render_text, CASES, FIX_HINTS,
    render_sarif, render_junit, render_json, render_robot, _sarif_level,
    fingerprint, load_baseline, write_baseline,
    _strip_library_prefix, is_verification,
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


def test_c2b_not_flagged_on_expected_status(tmp_path):
    # RequestsLibrary expected_status=<code> IS an oracle: the request fails if
    # the status differs. Must NOT be flagged C2b.
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
Get Users Returns 200
    GET    https://api.example.com/users    expected_status=200
"""
    assert "C2b" not in codes(tmp_path, body)


def test_c2b_flagged_on_expected_status_any(tmp_path):
    # expected_status=any disables the check. Since #75 this is reported as C9b
    # (oracle disabled), not conflated into the generic C2b (no oracle).
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
Status Disabled
    GET    https://api.example.com/users    expected_status=any
"""
    found = codes(tmp_path, body)
    assert "C9b" in found
    assert "C2b" not in found


def test_c2b_flagged_on_request_without_expected_status(tmp_path):
    # A bare request with no explicit status oracle is still C2b.
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
Bare Get
    GET    https://api.example.com/users
"""
    assert "C2b" in codes(tmp_path, body)


def test_c2b_flagged_on_wuks_around_non_oracle(tmp_path):
    # Wait Until Keyword Succeeds retrying a bare action asserts nothing - still C2b.
    body = """\
*** Test Cases ***
Retry An Action
    Wait Until Keyword Succeeds    5x    1s    Click    id:submit
"""
    assert "C2b" in codes(tmp_path, body)


def test_no_c2b_on_wuks_around_assertion(tmp_path):
    # The fix for #46: WUKS retrying a real assertion IS a verification. The scanner
    # must peek inside the wrapper's arguments, so this is not a no-oracle false positive.
    body = """\
*** Test Cases ***
Retry An Assertion
    Wait Until Keyword Succeeds    5x    1s    Should Be Equal    ${a}    ${b}
"""
    assert "C2b" not in codes(tmp_path, body)


def test_is_verification_peeks_inside_wuks():
    # Unit-level guard for the WUKS recursion in is_verification.
    assert is_verification("Wait Until Keyword Succeeds",
                           ["5x", "1s", "Should Be Equal", "${a}", "${b}"]) is True
    assert is_verification("Wait Until Keyword Succeeds",
                           ["5x", "1s", "Click", "id:submit"]) is False


# --- inline suppression (#49): # falsegreen: ignore[CODE] -------------------

def test_inline_ignore_specific_code(tmp_path):
    body = """\
*** Test Cases ***
Sleepy
    Sleep    1s    # falsegreen: ignore[C16]
    Should Be Equal    ${a}    1
"""
    assert "C16" not in codes(tmp_path, body)


def test_inline_ignore_bare_silences_all_on_the_line(tmp_path):
    body = """\
*** Test Cases ***
Sleepy
    Sleep    1s    # falsegreen: ignore
    Should Be Equal    ${a}    1
"""
    assert "C16" not in codes(tmp_path, body)


def test_inline_ignore_wrong_code_does_not_suppress(tmp_path):
    body = """\
*** Test Cases ***
Sleepy
    Sleep    1s    # falsegreen: ignore[C9]
    Should Be Equal    ${a}    1
"""
    assert "C16" in codes(tmp_path, body)


def test_inline_ignore_does_not_leak_to_other_tests(tmp_path):
    body = """\
*** Test Cases ***
A
    Sleep    1s    # falsegreen: ignore[C16]
    Should Be Equal    ${a}    1

B
    Sleep    2s
    Should Be Equal    ${b}    2
"""
    found = sorted((f.line, f.code) for f in _findings(tmp_path, body))
    # The suppressed Sleep is line 3; the sibling Sleep on line 8 still fires C16.
    assert ("C16" in {c for _, c in found}) and not any(c == "C16" and ln == 3 for ln, c in found)


def test_inline_ignore_requires_the_falsegreen_token(tmp_path):
    # FP guard: a bare "# ignore" without the falsegreen: token does not suppress.
    body = """\
*** Test Cases ***
Sleepy
    Sleep    1s    # ignore[C16]
    Should Be Equal    ${a}    1
"""
    assert "C16" in codes(tmp_path, body)


def test_inline_ignore_is_case_insensitive(tmp_path):
    # A lowercase code in the bracket suppresses the same upper-cased finding (#62).
    body = """\
*** Test Cases ***
Sleepy
    Sleep    1s    # falsegreen: ignore[c16]
    Should Be Equal    ${a}    1
"""
    assert "C16" not in codes(tmp_path, body)


def test_inline_ignore_on_a_continuation_line_suppresses_the_owning_call(tmp_path):
    # The finding is reported on the call's first physical line, but the ignore sits on
    # a wrapped (...) row; the suppression is folded onto the owning line (#64).
    body = """\
*** Test Cases ***
Wrapped
    Sleep
    ...    1 minute    # falsegreen: ignore[C16]
    Should Be Equal    ${a}    1
"""
    assert "C16" not in codes(tmp_path, body)


def test_c2b_not_flagged_on_expected_status_on_session(tmp_path):
    # The "On Session" form carries expected_status too.
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
Get On Session Returns 200
    GET On Session    api    /users    expected_status=200
"""
    assert "C2b" not in codes(tmp_path, body)


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


@pytest.mark.parametrize("step", [
    "${d}=    Get Current Date",
    "${s}=    Generate Random String",
    "${n}=    Evaluate    datetime.now()",
    "${r}=    Evaluate    random.randint(1, 9)",
    "${u}=    Evaluate    uuid.uuid4()",
    "${d}=    DateTime.Get Current Date",
    "${s}=    String.Generate Random String",
])
def test_c16_broadened_nondeterministic_sources(tmp_path, step):
    # Same non-determinism family as Sleep: a clock read, a random string, or an
    # Evaluate body reaching for datetime/random/uuid (#63).
    body = "*** Test Cases ***\nT\n    %s\n    Should Be Equal    ${a}    ${b}\n" % step
    assert "C16" in codes(tmp_path, body)


@pytest.mark.parametrize("step", [
    "${x}=    Evaluate    1 + 1",
    "${x}=    Evaluate    $base_seed + 1",
    "${n}=    Get Length    ${items}",
])
def test_no_c16_for_deterministic_keywords(tmp_path, step):
    # Plain arithmetic, a variable that merely contains 'seed', and a length read are
    # deterministic — the Evaluate scan keys on datetime./random./uuid. module access (#63).
    body = "*** Test Cases ***\nT\n    %s\n    Should Be Equal    ${a}    ${b}\n" % step
    assert "C16" not in codes(tmp_path, body)


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


# --- #65: CLEAN look-alikes (the smell's opposite must stay quiet) ----------

def test_no_c5_no_c7_for_distinct_arg_should_be_equal(tmp_path):
    # Two distinct operands: a real equality check, neither always-true nor self-compare.
    body = """\
*** Test Cases ***
Real Check
    Should Be Equal    ${actual}    ${expected}
"""
    found = codes(tmp_path, body)
    assert "C5" not in found
    assert "C7" not in found


def test_no_c5_for_should_be_true_with_a_real_expression(tmp_path):
    # Should Be True with a real comparison is a genuine check, not a tautology.
    body = """\
*** Test Cases ***
Real Condition
    Should Be True    ${count} > 0
"""
    assert "C5" not in codes(tmp_path, body)


def test_no_c32_for_a_test_without_skip_tag(tmp_path):
    # A normal tag is not a skip directive.
    body = """\
*** Test Cases ***
Runs Normally
    [Tags]    smoke
    Should Be Equal    ${a}    ${b}
"""
    assert "C32" not in codes(tmp_path, body)


def test_no_r1_for_a_test_with_real_checks_and_no_pass_execution(tmp_path):
    # No Pass Execution: the verification actually decides the verdict.
    body = """\
*** Test Cases ***
Honest
    Do Something
    Should Be Equal    ${a}    ${b}
"""
    assert "R1" not in codes(tmp_path, body)


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


# --- PL9 config-audit: project-layer (Robot run config) ----------------------

import importlib.util  # noqa: E402
from falsegreen_robot.scanner import audit_config  # noqa: E402

_HAS_TOML = bool(importlib.util.find_spec("tomllib") or importlib.util.find_spec("tomli"))


def test_config_audit_flags_skiponfailure_in_args(tmp_path):
    (tmp_path / "run.args").write_text("--skiponfailure flaky\n--outputdir out\n", encoding="utf-8")
    fs = audit_config(str(tmp_path))
    assert [f.code for f in fs] == ["PL9"]


def test_config_audit_flags_noncritical_in_args(tmp_path):
    (tmp_path / "ci.args").write_text("--noncritical wip\n", encoding="utf-8")
    assert {f.code for f in audit_config(str(tmp_path))} == {"PL9"}


def test_config_audit_clean_args(tmp_path):
    (tmp_path / "run.args").write_text("--outputdir out\n--loglevel DEBUG\n", encoding="utf-8")
    assert audit_config(str(tmp_path)) == []


def test_config_audit_no_config_is_empty(tmp_path):
    (tmp_path / "suite.robot").write_text("*** Test Cases ***\nT\n    Should Be Equal    1    1\n", encoding="utf-8")
    assert audit_config(str(tmp_path)) == []


def test_config_audit_finding_level_and_fix(tmp_path):
    (tmp_path / "run.args").write_text("--skiponfailure x\n", encoding="utf-8")
    d = audit_config(str(tmp_path))[0].dict()
    assert d["level"] == "project"
    assert d["fix"] == "remove --skiponfailure/--noncritical so a failing test fails the run"


@pytest.mark.skipif(not _HAS_TOML, reason="no TOML reader (tomllib is 3.11+, tomli not installed)")
def test_config_audit_robot_toml_skip_on_failure(tmp_path):
    (tmp_path / "robot.toml").write_text('skip-on-failure = ["flaky"]\n', encoding="utf-8")
    assert {f.code for f in audit_config(str(tmp_path))} == {"PL9"}


def test_config_audit_cli_exit_and_output(tmp_path):
    (tmp_path / "run.args").write_text("--skiponfailure x\n", encoding="utf-8")
    out = tmp_path / "rep.json"
    rc = main(["--config-audit", "--json", "--output", str(out), str(tmp_path)])
    assert rc == 10
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["findings"][0]["code"] == "PL9"


def test_pl9_in_catalog_and_fix_hints():
    from falsegreen_robot.scanner import CASES, FIX_HINTS
    assert "PL9" in CASES and "PL9" in FIX_HINTS


# --- #52: PL9 walks nested *.args, skipping IGNORED_DIRS ----------------------

def test_config_audit_flags_skiponfailure_in_nested_args(tmp_path):
    # A *.args below the root (tests/sub/run.args) must still be read - the audit
    # walks recursively, not just the base dir.
    sub = tmp_path / "tests" / "sub"
    sub.mkdir(parents=True)
    (sub / "run.args").write_text("--skiponfailure flaky\n", encoding="utf-8")
    assert {f.code for f in audit_config(str(tmp_path))} == {"PL9"}


def test_config_audit_clean_nested_args(tmp_path):
    # Same nested location, but no skiponfailure/noncritical -> clean.
    sub = tmp_path / "tests" / "sub"
    sub.mkdir(parents=True)
    (sub / "run.args").write_text("--outputdir out\n--loglevel DEBUG\n", encoding="utf-8")
    assert audit_config(str(tmp_path)) == []


def test_config_audit_skips_ignored_dirs_args(tmp_path):
    # An argfile inside an IGNORED_DIR (results/) is an artifact, not run config -
    # it must be skipped even though it carries the flag.
    res = tmp_path / "results"
    res.mkdir()
    (res / "x.args").write_text("--skiponfailure flaky\n", encoding="utf-8")
    assert audit_config(str(tmp_path)) == []


# --- output parity: SARIF / JUnit / baseline (issue #9) ----------------------

# A two-finding suite: C2 (high) in the empty test, plus C16 (low) and C7 (high)
# in a second test. Gives a mix of high and non-high findings for the level maps.
_MIXED = """\
*** Test Cases ***
Empty
    [Documentation]    nothing

Sleeps And Self Compares
    Sleep    2s
    Should Be Equal    ${x}    ${x}
"""


def test_sarif_level_map():
    assert _sarif_level("high") == "error"
    assert _sarif_level("low") == "warning"
    assert _sarif_level("off") == "note"
    assert _sarif_level("info") == "note"


def test_sarif_shape_and_tool_name(tmp_path):
    fs = _findings(tmp_path, _MIXED)
    doc = json.loads(render_sarif(fs))
    assert doc["version"] == "2.1.0"
    assert doc["$schema"].endswith("sarif-2.1.0.json")
    run = doc["runs"][0]
    assert run["tool"]["driver"]["name"] == "robotframework-falsegreen"
    # one rule per distinct emitted code, each with a defaultConfiguration level
    rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
    assert rule_ids == {f.code for f in fs}
    for r in run["tool"]["driver"]["rules"]:
        assert r["defaultConfiguration"]["level"] in ("error", "warning", "note")
    # results carry the level map and a startLine, plus judgment + pyramid tags
    by_code = {res["ruleId"]: res for res in run["results"]}
    assert by_code["C2"]["level"] == "error"        # high -> error
    assert by_code["C16"]["level"] == "warning"     # low  -> warning
    assert by_code["C7"]["level"] == "error"
    sample = run["results"][0]
    assert sample["locations"][0]["physicalLocation"]["region"]["startLine"] >= 1
    tags = sample["properties"]["tags"]
    assert any(t.startswith("J") for t in tags)         # judgment family
    assert any(t.startswith("level:") for t in tags)    # pyramid level


def test_junit_failure_and_skipped(tmp_path):
    fs = _findings(tmp_path, _MIXED)
    xml = render_junit(fs)
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    suite = root.find("testsuite")
    assert suite.get("name") == "robotframework-falsegreen"
    n_high = sum(1 for f in fs if CASES[f.code][1] == "high")
    assert suite.get("failures") == str(n_high)
    assert suite.get("skipped") == str(len(fs) - n_high)
    # high finding -> <failure>, low finding -> <skipped>
    cases = suite.findall("testcase")
    for c in cases:
        code = c.get("classname").split(".")[-1]
        if CASES[code][1] == "high":
            assert c.find("failure") is not None
            assert c.find("skipped") is None
        else:
            assert c.find("skipped") is not None
            assert c.find("failure") is None


def test_format_sarif_via_cli(tmp_path):
    f = tmp_path / "t.robot"
    f.write_text(_EMPTY_TEST, encoding="utf-8")
    out = tmp_path / "report.sarif"
    rc = main([str(f), "--format", "sarif", "--output", str(out)])
    assert rc == 20  # C2 is high
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["runs"][0]["results"][0]["ruleId"] == "C2"


def test_format_junit_via_cli(tmp_path):
    f = tmp_path / "t.robot"
    f.write_text(_EMPTY_TEST, encoding="utf-8")
    out = tmp_path / "report.xml"
    main([str(f), "--format", "junit", "--output", str(out)])
    body = out.read_text(encoding="utf-8")
    assert "<testsuite" in body and "C2" in body


def test_json_output_unchanged(tmp_path):
    """--json and --format json keep the historical envelope shape."""
    fs = _findings(tmp_path, _EMPTY_TEST)
    doc = json.loads(render_json(fs))
    assert doc["tool"] == "robotframework-falsegreen"
    assert "version" in doc and "judgments" in doc
    assert doc["findings"][0]["code"] == "C2"
    # the CLI alias produces byte-identical output to --format json
    f = tmp_path / "t.robot"
    f.write_text(_EMPTY_TEST, encoding="utf-8")
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    main([str(f), "--json", "--output", str(a)])
    main([str(f), "--format", "json", "--output", str(b)])
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


def test_fingerprint_ignores_line_number(tmp_path):
    """Same finding shifted down the file keeps its fingerprint (no line in the key)."""
    body_top = _MIXED
    body_shifted = "\n\n\n" + _MIXED  # push every test down three lines
    fs_top = _findings(tmp_path, body_top, name="a.robot")
    fs_shifted = _findings(tmp_path, body_shifted, name="a.robot")
    # match on (code, detail); the file path is the same name
    by_top = {(f.code, f.detail): fingerprint(f) for f in fs_top}
    by_shifted = {(f.code, f.detail): fingerprint(f) for f in fs_shifted}
    assert by_top == by_shifted
    assert all(len(v) == 16 for v in by_top.values())


def test_baseline_round_trip_write_read(tmp_path):
    fs = _findings(tmp_path, _MIXED)
    bl = tmp_path / "baseline.json"
    n = write_baseline(str(bl), fs)
    assert n == len(fs)
    loaded = load_baseline(str(bl))
    assert loaded == {fingerprint(f) for f in fs}


def test_baseline_suppresses_known_keeps_new(tmp_path):
    suite = tmp_path / "s.robot"
    suite.write_text(_MIXED, encoding="utf-8")
    # baseline records the current findings
    bl = tmp_path / "baseline.json"
    write_baseline(str(bl), scan([str(suite)]))
    # re-scan against the baseline: everything known is suppressed
    assert scan([str(suite)], baseline=load_baseline(str(bl))) == []
    # add a new failing test, only it survives the baseline filter
    suite.write_text(_MIXED + "\nBrand New\n    [Documentation]    empty\n",
                     encoding="utf-8")
    survivors = scan([str(suite)], baseline=load_baseline(str(bl)))
    assert [f.code for f in survivors] == ["C2"]
    assert survivors[0].test == "Brand New"


def test_load_baseline_missing_file_is_empty(tmp_path):
    assert load_baseline(str(tmp_path / "nope.json")) == set()


def test_write_baseline_cli_exits_zero_and_writes(tmp_path):
    f = tmp_path / "t.robot"
    f.write_text(_MIXED, encoding="utf-8")
    bl = tmp_path / "out-baseline.json"
    rc = main([str(f), "--write-baseline", str(bl)])
    assert rc == 0
    doc = json.loads(bl.read_text(encoding="utf-8"))
    assert doc["tool"] == "robotframework-falsegreen"
    assert doc["findings"]


def test_baseline_cli_suppresses_known(tmp_path):
    f = tmp_path / "t.robot"
    f.write_text(_MIXED, encoding="utf-8")
    bl = tmp_path / "bl.json"
    main([str(f), "--write-baseline", str(bl)])
    # with the baseline the run is green (known findings suppressed)
    assert main([str(f), "--baseline", str(bl)]) == 0


# --- RF3 (status form) + RF17 + C-parity (issue #19) -------------------------
# RF3 maps to C3 here (shared id with the siblings). The bare-call C3 was already
# covered; these add the form where the status IS captured but never asserted.

def test_c3_swallow_status_assigned_but_never_used(tmp_path):
    body = """\
*** Test Cases ***
Captures And Drops
    ${status}    ${value}=    Run Keyword And Ignore Error    Do Risky Thing
    Log    moving on
"""
    assert "C3" in codes(tmp_path, body)


def test_no_c3_when_swallowed_status_is_asserted(tmp_path):
    body = """\
*** Test Cases ***
Captures And Checks
    ${status}    ${value}=    Run Keyword And Ignore Error    Do Risky Thing
    Should Be Equal    ${status}    PASS
"""
    assert "C3" not in codes(tmp_path, body)


def test_no_c3_when_swallowed_value_is_used(tmp_path):
    body = """\
*** Test Cases ***
Uses The Value
    ${status}    ${value}=    Run Keyword And Ignore Error    Read Config
    Should Be Equal    ${value}    expected
"""
    assert "C3" not in codes(tmp_path, body)


def test_c3_return_status_assigned_but_never_used(tmp_path):
    body = """\
*** Test Cases ***
Return Status Dropped
    ${ok}=    Run Keyword And Return Status    Do Risky Thing
    Log    done
"""
    assert "C3" in codes(tmp_path, body)


def test_c3_status_form_in_keyword(tmp_path):
    body = """\
*** Keywords ***
Try The Thing
    ${status}    ${value}=    Run Keyword And Ignore Error    Do Risky Thing
    Log    swallowed
"""
    assert "C3" in codes(tmp_path, body, name="kw.resource")


# RF17 -> R6 (Robot-specific, low): Should Be True on a string literal.

def test_r6_should_be_true_string_literal(tmp_path):
    body = """\
*** Test Cases ***
Vacuous Check
    Should Be True    login succeeded
"""
    assert "R6" in codes(tmp_path, body)


def test_no_r6_when_should_be_true_is_an_expression(tmp_path):
    body = """\
*** Test Cases ***
Real Check
    Should Be True    ${count} > 0
"""
    assert "R6" not in codes(tmp_path, body)


def test_no_r6_for_constant_true_stays_c5(tmp_path):
    # ${TRUE} / true / 1 is the always-true constant (C5), not the literal-string R6.
    body = """\
*** Test Cases ***
Tautology
    Should Be True    ${TRUE}
"""
    cs = codes(tmp_path, body)
    assert "C5" in cs and "R6" not in cs


def test_no_r6_for_bare_variable_stays_c6(tmp_path):
    body = """\
*** Test Cases ***
Weak
    ${r}=    Get Status
    Should Be True    ${r}
"""
    cs = codes(tmp_path, body)
    assert "C6" in cs and "R6" not in cs


def test_no_r6_for_falsy_literal(tmp_path):
    # FINDING C: a falsy literal (0 / False / None) is NOT always truthy - the
    # Should Be True check can fail, so it is not a vacuous oracle. No R6.
    body = """\
*** Test Cases ***
Zero Literal
    Should Be True    0

False Literal
    Should Be True    False

None Literal
    Should Be True    None
"""
    assert "R6" not in codes(tmp_path, body)


# C9: Run Keyword And Expect Error with a catch-all pattern.

def test_c9_expect_error_catch_all_star(tmp_path):
    body = """\
*** Test Cases ***
Accepts Any Error
    Run Keyword And Expect Error    *    Do Risky Thing
"""
    assert "C9" in codes(tmp_path, body)


def test_c9_expect_error_glob_star_prefix(tmp_path):
    body = """\
*** Test Cases ***
Accepts Any Error Glob
    Run Keyword And Expect Error    GLOB:*    Do Risky Thing
"""
    assert "C9" in codes(tmp_path, body)


def test_no_c9_when_expect_error_pattern_is_specific(tmp_path):
    body = """\
*** Test Cases ***
Expects A Specific Error
    Run Keyword And Expect Error    ValueError: bad input    Do Risky Thing
"""
    assert "C9" not in codes(tmp_path, body)


def test_no_c9_when_expect_error_equals_a_specific_message(tmp_path):
    # FINDING A: EQUALS:<msg> matches the literal message <msg>, not any error.
    # EQUALS:* matches the literal string "*", a specific message - not a catch-all.
    body = """\
*** Test Cases ***
Expects The Exact Message
    Run Keyword And Expect Error    EQUALS:Boom    Do Risky Thing
"""
    assert "C9" not in codes(tmp_path, body)


def test_no_c9_when_expect_error_starts_with_a_specific_prefix(tmp_path):
    # FINDING A: STARTS:<prefix> is a specific matcher, not a catch-all.
    body = """\
*** Test Cases ***
Expects A Prefix
    Run Keyword And Expect Error    STARTS:Boom    Do Risky Thing
"""
    assert "C9" not in codes(tmp_path, body)


def test_no_c9_when_expect_error_equals_a_literal_star(tmp_path):
    # FINDING A: EQUALS:* matches the LITERAL string "*" (a specific message),
    # not any error. Only a bare * / GLOB:* / all-star pattern is the catch-all.
    body = """\
*** Test Cases ***
Expects The Literal Star Message
    Run Keyword And Expect Error    EQUALS:*    Do Risky Thing
"""
    assert "C9" not in codes(tmp_path, body)


def test_c9_expect_error_regexp_catch_all(tmp_path):
    # A REGEXP catch-all (.* / .+ / ^.*$) matches any message, so the oracle is
    # vacuous just like the glob star - C9.
    for pat in ("REGEXP:.*", "REGEXP:.+", "REGEXP:^.*$", "REGEXP:(.*)", "REGEXP:.*?"):
        body = f"""\
*** Test Cases ***
Expects Any Error Via Regex
    Run Keyword And Expect Error    {pat}    Do Risky Thing
"""
        assert "C9" in codes(tmp_path, body), pat


def test_no_c9_when_expect_error_regexp_is_specific(tmp_path):
    # A specific regex (anchored to a real message) is a real oracle, not a catch-all.
    body = """\
*** Test Cases ***
Expects A Specific Error
    Run Keyword And Expect Error    REGEXP:ValueError: .*    Do Risky Thing
"""
    assert "C9" not in codes(tmp_path, body)


def test_no_c9_when_bare_dot_star_is_glob(tmp_path):
    # A bare `.*` (no REGEXP: prefix) is glob, where `.` is literal, so it only
    # matches messages starting with a dot - not a catch-all.
    body = """\
*** Test Cases ***
Glob Dot Star
    Run Keyword And Expect Error    .*    Do Risky Thing
"""
    assert "C9" not in codes(tmp_path, body)


# C9 / prefix: an in-file dotted keyword is a LOCAL keyword and must not be stripped.

def test_strip_library_prefix_keeps_local_dotted_keyword(tmp_path):
    # A name that is a locally-defined keyword keeps its dotted form; anything else is
    # stripped of its library prefix as before.
    local = {"api.get"}
    assert _strip_library_prefix("api.GET", local) == "api.GET"
    assert _strip_library_prefix("RequestsLibrary.GET", local) == "GET"
    assert _strip_library_prefix("api.GET", None) == "GET"


def test_is_verification_local_dotted_keyword_not_read_as_http_method(tmp_path):
    # Without the local-keyword set, api.GET strips to GET and reads as a RequestsLibrary
    # status assertion. With it, the local keyword wins and is not an oracle by name.
    args = ["expected_status=200"]
    assert is_verification("api.GET", args) is True            # stripped -> GET
    assert is_verification("api.GET", args, {"api.get"}) is False


def test_c2b_when_only_call_is_local_dotted_keyword_no_oracle(tmp_path):
    # api.GET is defined in this file (a local keyword), so calling it with
    # expected_status must NOT be mistaken for RequestsLibrary's GET status assertion.
    # The keyword does not verify, so the test has no oracle -> C2b. Before the fix the
    # over-strip credited a phantom verification and masked this.
    body = """\
*** Keywords ***
api.GET
    Log    just an action, no oracle

*** Test Cases ***
Calls A Local Dotted Keyword
    api.GET    expected_status=200
"""
    assert "C2b" in codes(tmp_path, body)


def test_real_requests_library_get_still_recognized(tmp_path):
    # Regression guard: a genuine RequestsLibrary GET with expected_status is still an
    # oracle (no local keyword shadows it), so no C2b.
    body = """\
*** Test Cases ***
Real Http Status Assertion
    RequestsLibrary.GET    https://api.example.com/health    expected_status=200
"""
    assert "C2b" not in codes(tmp_path, body)


# C20: verification after a terminator ([Return]/Fail/Return From Keyword).

def test_c20_verification_after_return_in_keyword(tmp_path):
    body = """\
*** Keywords ***
Returns Early
    Do Something
    [Return]    ${x}
    Should Be Equal    ${a}    ${b}
"""
    assert "C20" in codes(tmp_path, body, name="kw.resource")


def test_c20_verification_after_fail_in_test(tmp_path):
    body = """\
*** Test Cases ***
Fails First
    Fail    stop here
    Should Be Equal    ${a}    ${b}
"""
    assert "C20" in codes(tmp_path, body)


def test_no_c20_when_verification_runs_before_return(tmp_path):
    body = """\
*** Keywords ***
Checks Then Returns
    Should Be Equal    ${a}    ${b}
    [Return]    ${x}
"""
    assert "C20" not in codes(tmp_path, body, name="kw.resource")


def test_c20_after_return_from_keyword(tmp_path):
    body = """\
*** Keywords ***
Bails Out
    Return From Keyword
    Should Be Equal    ${a}    ${b}
"""
    assert "C20" in codes(tmp_path, body, name="kw.resource")


def test_no_c20_when_fail_is_conditional_via_run_keyword_if(tmp_path):
    # FINDING B: a Fail guarded by Run Keyword If is conditional - the later
    # verification is reached when the condition is false, so it is NOT dead.
    body = """\
*** Test Cases ***
Conditional Fail Then Check
    Run Keyword If    ${cond}    Fail    boom
    Should Be Equal    ${a}    ${b}
"""
    assert "C20" not in codes(tmp_path, body)


def test_no_c20_when_fail_is_inside_native_if(tmp_path):
    # FINDING B: a Fail inside a native IF is conditional; the verification after
    # the END runs when the branch is not taken, so it is NOT dead.
    body = """\
*** Test Cases ***
Branching Fail Then Check
    IF    ${cond}
        Fail    boom
    END
    Should Be Equal    ${a}    ${b}
"""
    assert "C20" not in codes(tmp_path, body)


def test_no_c20_when_return_is_conditional(tmp_path):
    # FINDING B: Return From Keyword If / Pass Execution If are conditional
    # terminators - a verification after them still runs when the guard is false.
    body = """\
*** Keywords ***
Bails Conditionally
    Return From Keyword If    ${cond}    ${x}
    Should Be Equal    ${a}    ${b}
"""
    assert "C20" not in codes(tmp_path, body, name="kw.resource")


def test_c20_when_pass_execution_if_guard_is_const_true(tmp_path):
    # Codex on #20: a `...If` terminator with a constant-true guard (${TRUE}, true,
    # 1) always fires, so the following verification is dead - C20 must fire.
    body = """\
*** Test Cases ***
Always Passes First
    Pass Execution If    ${TRUE}    done
    Should Be Equal    ${a}    ${b}
"""
    assert "C20" in codes(tmp_path, body)


def test_c20_when_return_from_keyword_if_guard_is_const_true(tmp_path):
    # Codex on #20: lowercase `true` guard is also always-true; the check after the
    # forced return is dead.
    body = """\
*** Keywords ***
Bails Always
    Return From Keyword If    true    ${x}
    Should Be Equal    ${a}    ${b}
"""
    assert "C20" in codes(tmp_path, body, name="kw.resource")


def test_no_c20_when_pass_execution_if_guard_is_variable(tmp_path):
    # The fix must not weaken the conditional case: a variable guard still lets the
    # verification run when the condition is false, so it is NOT dead.
    body = """\
*** Test Cases ***
Maybe Passes
    Pass Execution If    ${cond}    skip
    Should Be Equal    ${a}    ${b}
"""
    assert "C20" not in codes(tmp_path, body)


def test_c20_after_unconditional_top_level_fail(tmp_path):
    # FINDING B: a bare top-level Fail is unconditional - the verification after it
    # is dead, so C20 still fires (the fix must not weaken the real case).
    body = """\
*** Test Cases ***
Always Fails First
    Fail    stop here
    Should Be Equal    ${a}    ${b}
"""
    assert "C20" in codes(tmp_path, body)


def test_c5_fires_on_live_should_be_true_constant(tmp_path):
    # BAD baseline: a reachable always-true check is C5 (and not dead, so no C20).
    body = """\
*** Test Cases ***
Live Constant Check
    Should Be True    ${TRUE}
"""
    found = codes(tmp_path, body)
    assert "C5" in found
    assert "C20" not in found


def test_c5_suppressed_on_dead_line_c20_only(tmp_path):
    # #81: the SAME always-true check AFTER a terminator is dead. The assertion
    # never runs, so its value-shape code (C5) is moot - C20 owns the line and C5
    # is suppressed, matching the Python reference (no C5+C20 double-report).
    body = """\
*** Keywords ***
Bails Then Checks Constant
    Return From Keyword
    Should Be True    ${TRUE}
"""
    on_dead_line = {f.code for f in _findings(tmp_path, body, name="kw.resource")
                    if f.line == 4}
    assert on_dead_line == {"C20"}


def test_c7_self_compare_suppressed_on_dead_line(tmp_path):
    # #81: C7 (self-compare) is part of the same value-shape family; a self-compare
    # after a terminator is dead and reported as C20 alone.
    body = """\
*** Keywords ***
Bails Then Self Compares
    Return From Keyword
    Should Be Equal    ${x}    ${x}
"""
    on_dead_line = {f.code for f in _findings(tmp_path, body, name="kw.resource")
                    if f.line == 4}
    assert on_dead_line == {"C20"}


# C37: duplicate [Template] data row.

def test_c37_duplicate_template_row(tmp_path):
    body = """\
*** Test Cases ***
Same Row Twice
    [Template]    Verify Addition
    1    2    3
    1    2    3
    4    5    9
"""
    assert "C37" in codes(tmp_path, body)


def test_no_c37_when_template_rows_are_distinct(tmp_path):
    body = """\
*** Test Cases ***
Distinct Rows
    [Template]    Verify Addition
    1    2    3
    4    5    9
"""
    assert "C37" not in codes(tmp_path, body)


# CC: commented-out verification keyword.

def test_cc_commented_out_should(tmp_path):
    body = """\
*** Test Cases ***
Oracle Switched Off
    Do Something
    # Should Be Equal    ${a}    ${b}
    Should Contain    ${log}    ok
"""
    assert "CC" in codes(tmp_path, body)


def test_cc_commented_out_page_should(tmp_path):
    body = """\
*** Test Cases ***
Commented Page Check
    Open Page
    # Page Should Contain    Welcome
    Should Be Equal    ${a}    ${b}
"""
    assert "CC" in codes(tmp_path, body)


def test_no_cc_for_prose_comment(tmp_path):
    body = """\
*** Test Cases ***
Plain Comment
    # this should be revisited later
    Should Be Equal    ${a}    ${b}
"""
    assert "CC" not in codes(tmp_path, body)


@pytest.mark.parametrize("prose", [
    "# Validate that the user sees the page",
    "# Verify the deploy worked",
    "# Should we keep this test?",
    "# Assert nothing here, just a note",
])
def test_no_cc_for_prose_starting_with_a_verification_verb(tmp_path, prose):
    # A verb at the start of prose is not a commented-out keyword call: the verb must
    # be followed by a call shape (capitalized name + arg separator / variable / EOL),
    # not a lowercase prose continuation (#61).
    body = "*** Test Cases ***\nProse\n    %s\n    Should Be Equal    ${a}    ${b}\n" % prose
    assert "CC" not in codes(tmp_path, body)


@pytest.mark.parametrize("call", [
    "# Should Be Equal    ${a}    ${b}",
    "# Verify Login",
    "# Element Should Be Visible",
])
def test_cc_still_fires_for_a_commented_keyword_call(tmp_path, call):
    # A real commented-out verification keyword (name then args/EOL) still fires (#61).
    body = "*** Test Cases ***\nOff\n    Do Something\n    %s\n    Log    done\n" % call
    assert "CC" in codes(tmp_path, body)


def test_new_codes_in_catalog_and_fix_hints():
    for code in ("C9", "C20", "C37", "CC", "R6", "R7"):
        assert code in CASES, code
        assert code in FIX_HINTS, code


# --- R7: templated test driven by a hollow in-file template keyword (issue #32)

def test_r7_in_file_hollow_template_keyword(tmp_path):
    # [Template] resolves to a user keyword in the SAME file that only acts
    # (Click/Go To) and never verifies -> every generated case has no oracle.
    body = """\
*** Test Cases ***
Navigates Each Page
    [Template]    Open And Click
    /home    button-1
    /about    button-2

*** Keywords ***
Open And Click
    [Arguments]    ${path}    ${selector}
    Go To    ${path}
    Click    ${selector}
"""
    assert "R7" in codes(tmp_path, body)


def test_no_r7_when_in_file_template_keyword_verifies(tmp_path):
    # The in-file template keyword contains a Should -> it is a real oracle, no R7.
    body = """\
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
"""
    assert "R7" not in codes(tmp_path, body)


def test_no_r7_when_template_keyword_is_external(tmp_path):
    # FP bound: the [Template] keyword is NOT defined in this file (imported from a
    # resource the scanner cannot see). It may verify via a hidden keyword, so the
    # scanner must stay silent - no R7, no false positive.
    body = """\
*** Settings ***
Resource    shared.resource

*** Test Cases ***
Runs Imported Template
    [Template]    Verify Addition From Resource
    1    2    3
    4    5    9
"""
    cs = codes(tmp_path, body)
    assert "R7" not in cs
    assert "C2b" not in cs


def test_no_r7_when_template_keyword_named_like_verifier(tmp_path):
    # A hollow keyword named like a verifier is already R2 on its definition; the
    # templated test is not double-flagged R7.
    body = """\
*** Test Cases ***
Uses A Named Verifier
    [Template]    Verify Page
    /home
    /about

*** Keywords ***
Verify Page
    [Arguments]    ${path}
    Go To    ${path}
    Click    submit
"""
    cs = codes(tmp_path, body)
    assert "R7" not in cs
    assert "R2" in cs


# --- Run Keywords precision (issue #33): the chain's segments are scanned ------

def test_no_c2b_when_run_keywords_chain_has_verification(tmp_path):
    # Run Keywords splits on AND; one segment is Should Be Equal -> a real oracle.
    body = """\
*** Test Cases ***
Chained With A Check
    Run Keywords    Click    button    AND    Should Be Equal    ${a}    ${b}
"""
    assert "C2b" not in codes(tmp_path, body)


def test_c2b_when_run_keywords_chain_has_no_verification(tmp_path):
    # A chain of only actions has no oracle -> still C2b.
    body = """\
*** Test Cases ***
Chained Actions Only
    Run Keywords    Click    button    AND    Go To    /home
"""
    assert "C2b" in codes(tmp_path, body)


# --- Codex review fixes: library prefix + Run Keywords forms ------------------

def test_no_c2b_on_library_prefixed_request_with_expected_status(tmp_path):
    # FINDING 1: `RequestsLibrary.GET ... expected_status=200` is an oracle. The
    # library prefix must be stripped before the HTTP-method check, so NOT C2b.
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
Prefixed Get Returns 200
    RequestsLibrary.GET    https://api.example.com/users    expected_status=200
"""
    assert "C2b" not in codes(tmp_path, body)


def test_no_c2b_on_library_prefixed_should(tmp_path):
    # FINDING 1: `BuiltIn.Should Be Equal` is a verification once the `BuiltIn.`
    # prefix is stripped -> NOT C2b.
    body = """\
*** Test Cases ***
Prefixed Assertion
    Do Something
    BuiltIn.Should Be Equal    ${a}    ${b}
"""
    assert "C2b" not in codes(tmp_path, body)


def test_no_c2b_on_resource_prefixed_verifier(tmp_path):
    # FINDING 1: a verify-prefixed user keyword reached via a resource alias
    # (`api.Verify Dashboard`) is recognized only after the prefix is stripped -
    # `api.verify...` does not start with VERIFY_PREFIXES. So NOT C2b.
    body = """\
*** Test Cases ***
Prefixed Verifier
    Do Login
    api.Verify Dashboard Loaded
"""
    assert "C2b" not in codes(tmp_path, body)


def test_no_c2b_when_run_keywords_no_and_has_verifier(tmp_path):
    # FINDING 2: with no literal AND, Robot runs EACH arg as its own no-arg keyword.
    # `Verify X` is a verifier user keyword -> the chain verifies -> NOT C2b.
    body = """\
*** Test Cases ***
No And Chain With Verifier
    Run Keywords    Log    Verify Page Loaded
"""
    assert "C2b" not in codes(tmp_path, body)


def test_c2b_when_run_keywords_no_and_only_actions(tmp_path):
    # FINDING 2: no-AND chain of only actions has no oracle -> still C2b.
    body = """\
*** Test Cases ***
No And Chain Actions Only
    Run Keywords    Open Page    Click Button
"""
    assert "C2b" in codes(tmp_path, body)


def test_no_c2b_when_run_keywords_and_segment_carries_expected_status(tmp_path):
    # FINDING 3: the AND segment's own args must reach is_verification, so the
    # RequestsLibrary expected_status oracle on the GET segment fires -> NOT C2b.
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
And Chain With Request Oracle
    Run Keywords    GET    https://api.example.com/users    expected_status=200    AND    Log    done
"""
    assert "C2b" not in codes(tmp_path, body)


def test_c2b_when_run_keywords_and_segment_has_no_verifier(tmp_path):
    # FINDING 3: an AND chain whose segments only act (no oracle) -> still C2b.
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
And Chain No Oracle
    Run Keywords    GET    https://api.example.com/users    AND    Log    done
"""
    assert "C2b" in codes(tmp_path, body)


def test_version_lockstep():
    # __version__ must equal pyproject.toml and CITATION.cff. Single equality-chain assert,
    # no conditional and no truthiness check, so the scanner's own self-scan stays clean.
    import re
    import pathlib
    from falsegreen_robot.scanner import __version__
    root = pathlib.Path(__file__).resolve().parent.parent

    def _ver(path, pat):
        m = re.search(pat, path.read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else None

    pyproject_v = _ver(root / "pyproject.toml", r'^version\s*=\s*"([^"]+)"')
    cff_v = _ver(root / "CITATION.cff", r'^version:\s*(\S+)')
    assert __version__ == pyproject_v == cff_v, (
        "version lockstep broken: __version__=%s pyproject=%s CITATION=%s"
        % (__version__, pyproject_v, cff_v))


# --- #47: C5 broadened — constant-true Set Variable If pins the expected oracle ---

def test_c5_set_variable_if_const_true_pins_expected(tmp_path):
    # The expected side is fixed to a constant the test chose via a const-true guard:
    # Should Be Equal then compares against that pinned constant - a tautology dressed up.
    body = """\
*** Test Cases ***
Pins The Oracle
    ${expected}=    Set Variable If    ${TRUE}    100
    ${actual}=    Compute Total
    Should Be Equal    ${actual}    ${expected}
"""
    assert "C5" in codes(tmp_path, body)


def test_no_c5_for_set_variable_if_with_runtime_guard(tmp_path):
    # One token away: a runtime-variable guard is normal branching, not a pinned
    # constant. The detector requires a literal constant-true guard, so this is quiet.
    body = """\
*** Test Cases ***
Real Branch
    ${expected}=    Set Variable If    ${ready}    100    200
    ${actual}=    Compute Total
    Should Be Equal    ${actual}    ${expected}
"""
    assert "C5" not in codes(tmp_path, body)


def test_no_c5_when_set_variable_if_value_not_used_as_expected(tmp_path):
    # Const-true guard, but the assigned value never reaches an assertion's expected
    # side - the flow is not proven, so the detector stays silent.
    body = """\
*** Test Cases ***
Unused Pin
    ${pinned}=    Set Variable If    ${TRUE}    100
    Log    ${pinned}
    Should Be Equal    ${actual}    ${other}
"""
    assert "C5" not in codes(tmp_path, body)


# --- #53: C44 — library assertion provably true for any value -----------------

def test_c44_should_contain_empty_string(tmp_path):
    # Every string contains the empty string, so the assertion can never fail.
    body = """\
*** Test Cases ***
Contains Empty
    Should Contain    ${result}    ${EMPTY}
"""
    assert "C44" in codes(tmp_path, body)


def test_no_c44_should_contain_two_free_variables(tmp_path):
    # One token away: two free variables is a real containment check (FP ceiling).
    body = """\
*** Test Cases ***
Contains Something
    Should Contain    ${result}    ${needle}
"""
    assert "C44" not in codes(tmp_path, body)


def test_c44_should_not_be_empty_on_constant(tmp_path):
    # A constant is never empty, so Should Not Be Empty on it is vacuous.
    body = """\
*** Test Cases ***
Never Empty
    Should Not Be Empty    ${TRUE}
"""
    assert "C44" in codes(tmp_path, body)


def test_no_c44_should_not_be_empty_on_variable(tmp_path):
    # A runtime variable can be empty, so the check is real - not C44.
    body = """\
*** Test Cases ***
Maybe Empty
    Should Not Be Empty    ${response}
"""
    assert "C44" not in codes(tmp_path, body)


def test_c44_should_be_empty_on_empty_literal(tmp_path):
    # The empty literal is always empty, so the assertion never fails.
    body = """\
*** Test Cases ***
Always Empty
    Should Be Empty    ${EMPTY}
"""
    assert "C44" in codes(tmp_path, body)


def test_no_c44_should_be_empty_on_variable(tmp_path):
    body = """\
*** Test Cases ***
Real Empty Check
    Should Be Empty    ${trailing}
"""
    assert "C44" not in codes(tmp_path, body)


def test_c44_length_should_be_empty_zero(tmp_path):
    # The empty literal has length 0, so the assertion is a tautology.
    body = """\
*** Test Cases ***
Empty Has Length Zero
    Length Should Be    ${EMPTY}    0
"""
    assert "C44" in codes(tmp_path, body)


def test_c44_length_should_be_after_literal_set_variable(tmp_path):
    # The subject was assigned a literal by an immediately-preceding Set Variable, and
    # the expected length matches that literal's length - vacuous (form 4).
    body = """\
*** Test Cases ***
Fixed Length
    ${s}=    Set Variable    hello
    Length Should Be    ${s}    5
"""
    assert "C44" in codes(tmp_path, body)


def test_no_c44_length_should_be_on_runtime_subject(tmp_path):
    # One token away: the subject is a runtime value (Get Text), so the length check
    # is real. The in-body literal trace does not fire.
    body = """\
*** Test Cases ***
Real Length Check
    ${s}=    Get Text    sel
    Length Should Be    ${s}    5
"""
    assert "C44" not in codes(tmp_path, body)


def test_should_be_true_empty_is_not_c44(tmp_path):
    # Should Be True ${EMPTY} is R6/C6 territory (bare variable), never C44.
    cs = codes(tmp_path, """\
*** Test Cases ***
T
    Should Be True    ${EMPTY}
""")
    assert "C44" not in cs


def test_c44_in_catalog_and_fix_hints():
    assert "C44" in CASES and "C44" in FIX_HINTS
    assert CASES["C44"][1] == "high" and CASES["C44"][2] == "J2"


# --- #50: project config file ([tool.falsegreen] / .falsegreen.toml) ----------

from falsegreen_robot.scanner import load_project_config  # noqa: E402

_SLEEPY = """\
*** Test Cases ***
Sleepy
    Sleep    1s
    Should Be Equal    ${a}    ${b}
"""


def test_config_disable_from_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.falsegreen]\ndisable = ["C16"]\n', encoding="utf-8")
    (tmp_path / "t.robot").write_text(_SLEEPY, encoding="utf-8")
    rc = main([str(tmp_path)])
    # C16 was the only finding; disabled via config -> clean run
    assert rc == 0


def test_config_disable_from_dotfile(tmp_path):
    (tmp_path / ".falsegreen.toml").write_text('disable = ["C16"]\n', encoding="utf-8")
    cfg = load_project_config(str(tmp_path))
    assert cfg["disable"] == {"C16"}


def test_config_pyproject_wins_over_dotfile(tmp_path):
    # First found wins, no merge: pyproject [tool.falsegreen] is read, .falsegreen.toml ignored.
    (tmp_path / "pyproject.toml").write_text(
        '[tool.falsegreen]\ndisable = ["C16"]\n', encoding="utf-8")
    (tmp_path / ".falsegreen.toml").write_text('disable = ["C2"]\n', encoding="utf-8")
    cfg = load_project_config(str(tmp_path))
    assert cfg["disable"] == {"C16"}


def test_config_diagnostics_on(tmp_path):
    (tmp_path / ".falsegreen.toml").write_text("diagnostics = true\n", encoding="utf-8")
    cfg = load_project_config(str(tmp_path))
    assert cfg["diagnostics"] is True


def test_config_long_test_overrides_threshold(tmp_path):
    (tmp_path / ".falsegreen.toml").write_text("long_test = 3\n", encoding="utf-8")
    cfg = load_project_config(str(tmp_path))
    assert cfg["long_test"] == 3
    # threaded as a parameter (not a mutated global): a 4-step test trips M2 at threshold 3
    steps = "\n".join("    Log    step %d" % i for i in range(4))
    body = "*** Test Cases ***\nLongish\n%s\n    Should Be Equal    ${a}    ${b}\n" % steps
    f = tmp_path / "s.robot"
    f.write_text(body, encoding="utf-8")
    on = {x.code for x in scan([str(f)], diagnostics=True, long_test=cfg["long_test"])}
    assert "M2" in on
    # the module global is untouched
    from falsegreen_robot.scanner import DIAGNOSTIC_THRESHOLDS
    assert DIAGNOSTIC_THRESHOLDS["long_test_steps"] == 10


def test_config_unknown_key_warns_to_stderr(tmp_path, capsys):
    (tmp_path / ".falsegreen.toml").write_text(
        'bogus_key = 1\ndisable = ["NOPE"]\n', encoding="utf-8")
    load_project_config(str(tmp_path))
    err = capsys.readouterr().err
    assert "unknown config key 'bogus_key'" in err
    assert "unknown code 'NOPE'" in err


def test_config_absent_is_default(tmp_path):
    cfg = load_project_config(str(tmp_path))
    assert cfg == {"disable": set(), "diagnostics": False,
                   "long_test": None, "verify_keywords": []}


# --- #54: config-declared custom verification patterns ------------------------

def test_verify_keywords_suppresses_c2b(tmp_path):
    # A custom verifier named via config suppresses the C2b that fires without it.
    body = """\
*** Test Cases ***
Uses A Custom Verifier
    Do Login
    Confirm Balance    100
"""
    f = tmp_path / "t.robot"
    f.write_text(body, encoding="utf-8")
    assert "C2b" in {x.code for x in scan([str(f)])}
    assert "C2b" not in {x.code for x in scan([str(f)], extra_verify={"confirm"})}


def test_verify_keywords_matches_full_normalized_name_not_leaf(tmp_path):
    # `Expect Response Ok` matches the pattern `expect response` as a substring of the
    # FULL normalized name, not a split leaf.
    assert is_verification("Expect Response Ok", [], None, {"expect response"}) is True
    assert is_verification("Do Something Else", [], None, {"expect response"}) is False


def test_verify_keywords_empty_set_is_byte_identical(tmp_path):
    # Opt-in: no patterns -> identical behavior (the custom verifier is not recognized).
    body = """\
*** Test Cases ***
No Custom Verifier
    Do Login
    Confirm Balance    100
"""
    f = tmp_path / "t.robot"
    f.write_text(body, encoding="utf-8")
    assert {x.code for x in scan([str(f)])} == {x.code for x in scan([str(f)], extra_verify=set())}


# --- #74: R8 / R8b - verification lives only in [Setup]/[Teardown] ------------

def test_r8_verification_only_in_test_setup(tmp_path):
    # A verifying [Setup] checks preconditions BEFORE the body acts: the body can
    # break and the suite stays green. Setup form is high.
    body = """\
*** Test Cases ***
Setup Verifies
    [Setup]    Should Be Equal    ${a}    ${b}
    Log    body runs but verifies nothing
"""
    assert "R8" in codes(tmp_path, body)


def test_r8_verification_only_in_suite_test_setup(tmp_path):
    # Suite-level Test Setup is inherited by a test with no body oracle -> R8.
    body = """\
*** Settings ***
Test Setup    Should Be Equal    ${a}    ${b}

*** Test Cases ***
Inherits Verifying Setup
    Log    body runs but verifies nothing
"""
    assert "R8" in codes(tmp_path, body)


def test_r8b_verification_only_in_teardown(tmp_path):
    # A verifying [Teardown]-only runs even on body failure, on a separate axis. Low.
    body = """\
*** Test Cases ***
Teardown Verifies
    Do Something
    [Teardown]    Verify Cleanup
"""
    found = codes(tmp_path, body)
    assert "R8b" in found
    assert "R8" not in found


def test_no_r8_when_body_verifies(tmp_path):
    # One token away: the body has its own oracle, so the [Setup] check is fine.
    body = """\
*** Test Cases ***
Body Verifies
    [Setup]    Should Be Equal    ${a}    ${b}
    Should Be Equal    ${x}    ${y}
"""
    assert "R8" not in codes(tmp_path, body)


def test_no_r8_when_setup_does_not_verify(tmp_path):
    # A non-verifying [Setup] with a body oracle is a normal test.
    body = """\
*** Test Cases ***
Normal
    [Setup]    Open Browser    http://x
    Should Be Equal    ${x}    ${y}
"""
    assert codes(tmp_path, body) == set()


def test_test_setup_overrides_suite_setup_for_r8(tmp_path):
    # The test's own non-verifying [Setup] overrides the verifying suite Test Setup,
    # so no R8 - but the body still has no oracle, so C2b fires instead.
    body = """\
*** Settings ***
Test Setup    Should Be Equal    ${a}    ${b}

*** Test Cases ***
Overrides Setup
    [Setup]    Open Browser    http://x
    Log    nothing verified
"""
    found = codes(tmp_path, body)
    assert "R8" not in found
    assert "C2b" in found


# --- #75: C9b - RequestsLibrary expected_status=any is a disabled oracle -------

def test_c9b_expected_status_any(tmp_path):
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
Status Disabled
    GET    https://api.example.com/users    expected_status=any
"""
    found = codes(tmp_path, body)
    assert "C9b" in found
    assert "C2b" not in found  # no longer conflated with 'no oracle'


def test_c9b_expected_status_anything_on_session(tmp_path):
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
Status Disabled
    GET On Session    api    /users    expected_status=anything
"""
    assert "C9b" in codes(tmp_path, body)


def test_no_c9b_for_specific_status(tmp_path):
    # One token away: a specific code keeps the oracle alive - no C9b, no C2b.
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
Specific
    GET    https://api.example.com/users    expected_status=200
"""
    found = codes(tmp_path, body)
    assert "C9b" not in found
    assert "C2b" not in found


# --- #76: C11a - self-confirming literal (expected is a copy of the actual) ----

def test_c11a_self_confirming_literal(tmp_path):
    body = """\
*** Test Cases ***
Self Confirming
    ${value}=    Get Value From Sut
    ${expected}=    Set Variable    ${value}
    Should Be Equal    ${value}    ${expected}
"""
    found = codes(tmp_path, body)
    assert "C11a" in found


def test_no_c11a_when_expected_is_independent(tmp_path):
    # One token away: the expected value is a literal, not a copy of the actual.
    body = """\
*** Test Cases ***
Honest
    ${value}=    Get Value From Sut
    ${expected}=    Set Variable    42
    Should Be Equal    ${value}    ${expected}
"""
    assert "C11a" not in codes(tmp_path, body)


def test_c11a_does_not_displace_plain_self_compare_c7(tmp_path):
    # The plain ${x} ${x} form stays C7, not C11a (C7 owns the line).
    body = """\
*** Test Cases ***
Plain Self
    Should Be Equal    ${x}    ${x}
"""
    found = codes(tmp_path, body)
    assert "C7" in found
    assert "C11a" not in found


# --- P2 regression: fixture NONE clears inherited fixture; C11a reassignment ---

def test_setup_none_clears_inherited_verifying_test_setup(tmp_path):
    # [Setup] NONE explicitly opts out of a verifying suite Test Setup, so R8 must NOT
    # fire; the body still verifies nothing, so it is a plain C2b.
    body = """\
*** Settings ***
Test Setup    Should Be Equal    ${a}    ${b}

*** Test Cases ***
Opts Out Of Setup
    [Setup]    NONE
    Log    nothing
"""
    found = codes(tmp_path, body)
    assert "R8" not in found
    assert "C2b" in found


def test_teardown_none_clears_inherited_verifying_test_teardown(tmp_path):
    # [Teardown] NONE opts out of a verifying suite Test Teardown -> not R8b, but C2b.
    body = """\
*** Settings ***
Test Teardown    Verify Cleanup

*** Test Cases ***
Opts Out Of Teardown
    Log    nothing
    [Teardown]    NONE
"""
    found = codes(tmp_path, body)
    assert "R8b" not in found
    assert "C2b" in found


def test_no_c11a_on_snapshot_then_recompute(tmp_path):
    # An honest snapshot-recompute-compare: ${expected} snapshots ${value}, then ${value}
    # is recomputed before the assertion. The expected side is no longer a copy of the
    # actual, so C11a must NOT fire.
    body = """\
*** Test Cases ***
Snapshot Then Recompute
    ${value}=    Get Value
    ${expected}=    Set Variable    ${value}
    ${value}=    Recompute
    Should Be Equal    ${value}    ${expected}
"""
    assert "C11a" not in codes(tmp_path, body)


# --- #78: field-validation precision fixes ------------------------------------
# FP-1 (C3): a status consumed only by a control-block header was misread as unused.
def test_c3_status_truly_unused(tmp_path):
    # The status is captured and then nothing reads it - the failure is dropped (C3).
    body = """\
*** Test Cases ***
Dropped Status
    ${s}=    Run Keyword And Return Status    Should Exist    x
    Log    moving on
"""
    assert "C3" in codes(tmp_path, body)


def test_no_c3_status_read_by_if_header(tmp_path):
    # The idiomatic conditional: the status drives an IF header. It is read, so no C3.
    body = """\
*** Test Cases ***
Conditional On Status
    ${s}=    Run Keyword And Return Status    Should Exist    x
    IF    ${s}
        Log    it exists
    END
"""
    assert "C3" not in codes(tmp_path, body)


def test_no_c3_status_read_by_while_header(tmp_path):
    # A WHILE header reads the status too (the negated retry form).
    body = """\
*** Test Cases ***
Loop Until Status
    ${s}=    Run Keyword And Return Status    Should Exist    x
    WHILE    not ${s}
        Log    retrying
        ${s}=    Run Keyword And Return Status    Should Exist    x
    END
"""
    assert "C3" not in codes(tmp_path, body)


# FP-2 (R2): a soft-assert wrapper around a real assertion is a verification.
def test_r2_continue_on_failure_around_non_oracle(tmp_path):
    # The wrapper runs Log, which verifies nothing - the verifier keyword is hollow (R2).
    body = """\
*** Keywords ***
Verify X
    Run Keyword And Continue On Failure    Log    msg
"""
    assert "R2" in codes(tmp_path, body)


def test_no_r2_continue_on_failure_around_assertion(tmp_path):
    # Continue On Failure wrapping a real comparison is the standard soft-assert idiom.
    body = """\
*** Keywords ***
Verify X
    Run Keyword And Continue On Failure    Should Be Equal    ${a}    ${b}
"""
    assert "R2" not in codes(tmp_path, body)


def test_no_r2_warn_on_failure_around_assertion(tmp_path):
    # The Warn On Failure variant is the same soft-assert wrapper.
    body = """\
*** Keywords ***
Verify X
    Run Keyword And Warn On Failure    Should Be Equal    ${a}    ${b}
"""
    assert "R2" not in codes(tmp_path, body)


# FP-3 (C9b): expected_status=any with a manual status assert on the next line.
def test_c9b_expected_status_any_without_manual_assert(tmp_path):
    # The request oracle is disabled and nothing checks the status afterwards (C9b).
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
Disabled No Followup
    ${r}=    GET    https://api.example.com/users    expected_status=any
    Log    ${r.status_code}
"""
    assert "C9b" in codes(tmp_path, body)


def test_no_c9b_when_status_asserted_manually(tmp_path):
    # The author disabled the request oracle on purpose to check the status by hand.
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
Manual Status Check
    ${r}=    GET    https://api.example.com/users    expected_status=any
    Should Be Equal As Integers    ${r.status_code}    200
"""
    assert "C9b" not in codes(tmp_path, body)

def test_no_c9b_when_status_asserted_via_item_access(tmp_path):
    # The dict-item form of the same manual status check also suppresses C9b.
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
Manual Status Item
    ${r}=    GET    https://api.example.com/users    expected_status=any
    Should Be Equal As Integers    ${r}[status_code]    200
"""
    assert "C9b" not in codes(tmp_path, body)


# --- C31: captured value never used (#34) ----------------------------------
def test_c31_captured_value_never_used(tmp_path):
    # A value is captured and dropped while the test verifies an unrelated pair.
    body = """\
*** Test Cases ***
Captured Dead
    ${x}=    Get Text    //loc
    Should Be Equal    ${a}    ${b}
"""
    cs = codes(tmp_path, body)
    assert "C31" in cs
    # The test does have an oracle, so it is not the no-verification case.
    assert "C2b" not in cs


def test_c31_is_low_confidence(tmp_path):
    # Shipped behind low confidence on purpose, precision-first.
    assert CASES["C31"][1] == "low"


def test_no_c31_when_value_is_logged_later(tmp_path):
    # A later Log of the captured name counts as a use, so the capture is alive.
    body = """\
*** Test Cases ***
Logged
    ${x}=    Get Text    //loc
    Log    ${x}
    Should Be Equal    ${a}    ${b}
"""
    assert "C31" not in codes(tmp_path, body)


def test_no_c31_when_value_is_asserted(tmp_path):
    # The captured value flows straight into the oracle, so it is used.
    body = """\
*** Test Cases ***
Used In Assert
    ${x}=    Get Text    //loc
    Should Be Equal    ${x}    foo
"""
    assert "C31" not in codes(tmp_path, body)


def test_no_c31_when_used_in_evaluate_string(tmp_path):
    # A name spliced into a later Evaluate expression is a textual mention, so used.
    body = """\
*** Test Cases ***
Eval Use
    ${x}=    Get Text    //loc
    ${y}=    Evaluate    int(${x}) + 1
    Should Be Equal    ${y}    5
"""
    assert "C31" not in codes(tmp_path, body)


def test_no_c31_when_used_in_teardown(tmp_path):
    # A teardown that reads the captured name keeps it alive.
    body = """\
*** Test Cases ***
Teardown Use
    ${x}=    Get Text    //loc
    Should Be Equal    ${a}    ${b}
    [Teardown]    Log    ${x}
"""
    assert "C31" not in codes(tmp_path, body)


def test_no_c31_for_set_variable_assignment(tmp_path):
    # Set Variable is skipped: the no-oracle / pinned-oracle forms are other codes.
    body = """\
*** Test Cases ***
Set Var Unused
    ${x}=    Set Variable    foo
    Should Be Equal    ${a}    ${b}
"""
    assert "C31" not in codes(tmp_path, body)


def test_no_c31_for_swallow_status(tmp_path):
    # An unused swallow status is C3, never re-reported as C31.
    body = """\
*** Test Cases ***
Swallow
    ${s}=    Run Keyword And Return Status    Do Thing
    Should Be Equal    ${a}    ${b}
"""
    cs = codes(tmp_path, body)
    assert "C31" not in cs
    assert "C3" in cs


# --- robot per-test output format (#8) --------------------------------------
def test_render_robot_groups_findings_under_their_test(tmp_path):
    body = """\
*** Test Cases ***
Captured Dead
    ${x}=    Get Text    //loc
    Should Be Equal    ${a}    ${b}

Tautology
    Should Be True    ${TRUE}
"""
    fs = _findings(tmp_path, body)
    out = render_robot(fs)
    # Each owning test name appears as a heading, with its codes beneath it.
    assert "Captured Dead" in out
    assert "Tautology" in out
    assert "C31" in out and "C5" in out


def test_render_robot_buckets_file_level_findings(tmp_path):
    # A commented-out verification has no owning test, so it lands in the bucket.
    body = """\
*** Test Cases ***
Real
    Should Be Equal    ${a}    ${b}
    # Should Be Equal    ${a}    ${c}
"""
    fs = _findings(tmp_path, body)
    out = render_robot(fs)
    assert "[suite-level]" in out
    assert "CC" in out


def test_render_robot_empty_is_clean_message(tmp_path):
    assert render_robot([]).startswith("rffalsegreen: no false-positive")


def test_format_robot_via_cli(tmp_path):
    f = tmp_path / "t.robot"
    f.write_text(_EMPTY_TEST, encoding="utf-8")
    out = tmp_path / "report.txt"
    rc = main([str(f), "--format", "robot", "--output", str(out)])
    assert rc == 20  # C2 is high
    body = out.read_text(encoding="utf-8")
    assert "C2" in body


# --- Global output dedup (file, line, code, detail), #64 ---------------------

def test_global_dedup_collapses_true_duplicate(tmp_path, monkeypatch):
    """Two passes emitting the same (file, line, code, detail) yield ONE finding.
    Robot detectors break/continue to avoid double-firing today, so the dedup is a
    safety net: force a duplicate at the analyze layer and assert scan collapses it,
    matching the Python reference scanner."""
    import falsegreen_robot.scanner as sc
    body = """*** Test Cases ***
T
    Sleep    1s
"""
    f = tmp_path / "t.robot"
    f.write_text(body, encoding="utf-8")

    def fake_analyze_file(path, *a, **k):
        return [sc.Finding(str(f), 3, "T", "C16", ""),
                sc.Finding(str(f), 3, "T", "C16", "")]

    monkeypatch.setattr(sc, "analyze_file", fake_analyze_file)
    out = sc.scan([str(f)])
    assert len([x for x in out if x.code == "C16" and x.line == 3]) == 1


def test_global_dedup_keeps_two_codes_on_same_line(tmp_path):
    """Two independent detector families fire on the same LIVE line and both
    survive: `Run Keyword And Expect Error    *    Get    http://10.0.0.1` is both
    C9 (catch-all error pattern) and C23 (hard-coded IP URL). Neither is gated by
    dead-line suppression, so this is a legitimate same-line multi-code per the
    contract, mirroring the JS sibling test (C20+C16). The dedup key includes the
    code, so neither collapses the other."""
    body = """*** Test Cases ***
T
    Run Keyword And Expect Error    *    Get    http://10.0.0.1
"""
    f = tmp_path / "t.robot"
    f.write_text(body, encoding="utf-8")
    on_line_3 = {x.code for x in scan([str(f)]) if x.line == 3}
    assert "C9" in on_line_3
    assert "C23" in on_line_3
