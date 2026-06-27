"""Tests for robotframework-falsegreen. Each fixture is a tiny .robot file."""
import pytest
import json

from falsegreen_robot.scanner import (
    analyze_file, scan, group_of, main, resolve_output_path,
    _render_text, CASES, FIX_HINTS,
    render_sarif, render_junit, render_json, _sarif_level,
    fingerprint, load_baseline, write_baseline,
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
    # expected_status=any disables the check: no oracle, still C2b.
    body = """\
*** Settings ***
Library    RequestsLibrary

*** Test Cases ***
Status Disabled
    GET    https://api.example.com/users    expected_status=any
"""
    assert "C2b" in codes(tmp_path, body)


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
