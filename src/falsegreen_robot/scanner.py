#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
robotframework-falsegreen: deterministic false-positive scanner for Robot Framework tests.

Parses .robot files with the official Robot Framework parser (robot.api.get_model)
- no execution - and flags test cases that pass green without protecting anything:
a test with no verification keyword, a swallowed Run Keyword And Ignore Error, an
always-true Should Be True ${TRUE}, a self-compare, Sleep used as a wait, a skipped
test. Sibling of falsegreen (Python/pytest) and falsegreen-js (JS/TS).

Output: readable text (default) or JSON (--json).
Exit: 0 clean, 10 low-confidence only, 20 high-confidence present.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

__version__ = "0.1.0"
TOOL_URI = "https://github.com/vinicq/robotframework-falsegreen"

# --- case catalog. code -> (title, confidence, judgment J1-J6) -------------
JUDGMENTS = {
    "J1": "does the verification run?",
    "J2": "is the oracle independent of the code?",
    "J4": "does it check enough, and the right thing?",
    "J5": "is it coupled / hard to maintain?",
}
CASES = {
    "C2":  ("empty test case, task, or keyword (no keywords run)", "high", "J1"),
    "C2b": ("runs keywords but no verification keyword (no oracle)", "low", "J1"),
    "C3":  ("Run Keyword And Ignore Error/Return Status swallows the failure and the status is never asserted", "high", "J1"),
    "C5":  ("always-true check (Should Be True ${TRUE} / Should Be Equal with equal literals)", "high", "J2"),
    "C6":  ("weak check — Should Be True on a bare variable (truthiness only, not a comparison)", "low", "J4"),
    "C7":  ("self-compare (Should Be Equal ${x} ${x})", "high", "J2"),
    "C16": ("Sleep used as synchronization (result depends on timing)", "low", "J1"),
    "C23": ("hard-coded IP-address URL in test data (environment coupling / mystery guest)", "low", "J6"),
    "C21": ("verification only runs conditionally (inside IF / Run Keyword If) — it may never execute", "low", "J1"),
    "C32": ("skipped test (robot:skip / Skip) never runs", "low", "J1"),
    "R1":  ("Pass Execution forces the test to pass regardless of any check (forced green)", "high", "J1"),
    "R2":  ("user keyword named like a verifier (Verify/Assert/Should...) but its body contains no verification — a hollow oracle", "low", "J1"),
    "R3":  ("*** Test Cases *** section inside a .resource file — invalid; the cases never run", "high", "J1"),
    "R4":  ("No Operation is the only step — the test/task/keyword does nothing", "high", "J1"),
    "R5":  ("[Template] with no data rows — the templated test is generated with zero cases", "high", "J1"),
    # --- diagnostic group (maintainability; default off, opt-in via --diagnostics) ---
    "D2":  ("control flow (IF/FOR/WHILE/TRY) at the test/task level — the guide advises against it", "off", "J4"),
    # --- coupling group (structure; default off, opt-in) ----------------------
    "M2":  ("test/task has too many steps (the guide suggests max ~10)", "off", "J5"),
    # --- project layer (config-audit only; emitted by --config-audit, never by
    # the per-file scan). The suite reports green by run configuration. ---------
    "PL9": ("skip-on-failure / noncritical in the run config turns a failing test into a non-fatal pass (legacy, removed in RF 4+)", "low", "J1"),
}

# Default thresholds for the opt-in groups (overridable later via config).
DIAGNOSTIC_THRESHOLDS = {"long_test_steps": 10}


def group_of(code):
    """false-positive (C*/R*) / diagnostic (D*) / coupling (M*) / project (PL*) — mirrors the siblings."""
    if code.startswith("PL"):
        return "project"
    if code.startswith("D"):
        return "diagnostic"
    if code.startswith("M"):
        return "coupling"
    return "false-positive"


# One-line remediation per case: what to change so the test verifies something.
# Short, imperative, no trailing period. Surfaced in the status report (text +
# JSON `fix` field). A code missing here renders no fix line, never crashes.
FIX_HINTS = {
    "C2":  "add keywords that exercise and verify the behaviour",
    "C2b": "add a verification keyword (Should..., a library assertion)",
    "C3":  "assert the returned status, or let the failure propagate",
    "C5":  "compare against an independent expected value, not a constant",
    "C6":  "compare the value (Should Be Equal), not just its truthiness",
    "C7":  "compare against an independent expected value, not the same variable",
    "C16": "wait for the condition (Wait Until...) instead of Sleep",
    "C21": "move the verification out of the IF/Run Keyword If so it always runs",
    "C23": "read the URL from a variable/resource, not a hard-coded IP",
    "C32": "remove the skip, or document why with a reason",
    "R1":  "remove Pass Execution; let the checks decide the result",
    "R2":  "make the verifier keyword actually assert, or rename it",
    "R3":  "move the test cases to a .robot suite; .resource holds keywords only",
    "R4":  "replace No Operation with real steps and a verification",
    "R5":  "add data rows to the [Template], or remove the template",
    "D2":  "move control flow into a keyword; keep the test case flat",
    "M2":  "split the long test into focused cases or extract keywords",
    "PL9": "remove --skiponfailure/--noncritical so a failing test fails the run",
}

# Test-pyramid level by imported library. A browser/mobile driver is E2E; an
# HTTP client or a database library crosses an I/O boundary, so it is
# integration; neither leaves the suite at unit level.
E2E_LIBRARIES = {"seleniumlibrary", "selenium2library", "browser", "appiumlibrary"}
INTEGRATION_LIBRARIES = {
    "requestslibrary", "restinstance", "rest", "databaselibrary", "rpa.http",
}


def _collect_libraries(model):
    """Library names imported in the suite's *** Settings *** section."""
    libs = []
    for section in getattr(model, "sections", None) or []:
        for item in getattr(section, "body", None) or []:
            if type(item).__name__ == "LibraryImport":
                nm = getattr(item, "name", "") or ""
                if nm:
                    libs.append(nm)
    return libs


def detect_pyramid_level(model):
    """Map the suite to a pyramid level from its imported libraries: 'e2e' (browser
    or mobile driver), 'integration' (HTTP client or database library), or 'unit'
    (neither). Broadest wins. A real API/DB library in a test the author treats as
    unit is itself the smell, surfaced by the level mismatch."""
    norm = {_norm(name) for name in _collect_libraries(model)}
    if norm & E2E_LIBRARIES:
        return "e2e"
    if norm & INTEGRATION_LIBRARIES:
        return "integration"
    return "unit"

# --- verification vocabulary (the oracle), across Robot libraries ----------
# Dominant convention: the word "Should". Plus library-specific forms.
REST_SCHEMA = {"Integer", "Number", "String", "Boolean", "Object", "Array", "Null", "Missing"}
BROWSER_OPS = {"==", "!=", "contains", "not contains", "validate", "matches",
               ">", "<", ">=", "<=", "*=", "^=", "$=", "then"}
VERIFY_PREFIXES = ("verify", "assert", "validate", "check ")
SWALLOW_KEYWORDS = {"run keyword and ignore error", "run keyword and return status"}


def _norm(name):
    return (name or "").strip().lower()


def is_verification(keyword, args):
    """True if this keyword call verifies an expected result (is an oracle)."""
    if keyword is None:
        return False
    n = _norm(keyword)
    if "should" in n:
        return True                              # BuiltIn/Collections/String/Selenium/...
    if keyword in REST_SCHEMA:
        return True                              # RESTinstance schema assertions
    if n.startswith(VERIFY_PREFIXES):
        return True                              # custom Verify*/Assert*/Validate*/Check *
    if n.startswith("wait until") and any(w in n for w in ("contain", "visible", "present")):
        return True                              # Selenium/Appium waits that fail on timeout
    if n.startswith("get ") and any(a in BROWSER_OPS for a in (args or ())):
        return True                              # Browser assertion engine: Get ... == expected
    return False


def is_swallow(keyword):
    return _norm(keyword) in SWALLOW_KEYWORDS


def _looks_constant_true(arg):
    return _norm(arg) in ("${true}", "true", "1", "${1}")


_BARE_VAR_RE = re.compile(r"^[\$@&]\{[^{}]+\}$")
# A URL whose host is a literal IP address: strong signal of environment coupling
# (the test points at a fixed machine). A hostname URL is too common in E2E to flag.
_IP_URL_RE = re.compile(r"https?://\d{1,3}(?:\.\d{1,3}){3}\b")
# Body item types that actually do something (vs. settings like [Documentation]).
_EXECUTABLE_TYPES = {"KeywordCall", "If", "For", "While", "Try", "Var",
                     "ReturnStatement", "Return", "TemplateArguments"}


def _is_bare_variable(arg):
    """True for a lone variable like ${x} (no comparison/expression) — a weak oracle
    when passed to Should Be True (truthiness only)."""
    return bool(_BARE_VAR_RE.match((arg or "").strip()))


def _body_has_executable(node):
    """True if the body has any item that runs (a keyword call, a control block, a
    variable assignment, a return, or template data) — not only settings."""
    return any(type(i).__name__ in _EXECUTABLE_TYPES
               for i in (getattr(node, "body", None) or []))


def _only_no_operation(calls):
    """True if there is at least one call and every one is `No Operation`."""
    return bool(calls) and all(_norm(c.keyword) == "no operation" for c in calls)


# --- AST walk over the Robot model -----------------------------------------
def _keyword_calls(node):
    """Yield every KeywordCall in a block, descending into IF/FOR/TRY/WHILE."""
    for item in getattr(node, "body", None) or []:
        cls = type(item).__name__
        if cls == "KeywordCall":
            yield item
        if hasattr(item, "body"):
            yield from _keyword_calls(item)


def _top_level_keyword_calls(testcase):
    """KeywordCalls directly in the test body (not nested in IF/FOR/TRY/WHILE)."""
    return [i for i in (getattr(testcase, "body", None) or [])
            if type(i).__name__ == "KeywordCall"]


def _has_control_block(testcase):
    return any(type(i).__name__ in ("If", "For", "While", "Try")
               for i in (getattr(testcase, "body", None) or []))


def _rkif_verifies(call):
    """A `Run Keyword If`/`Unless` whose arguments name a verification keyword -
    that is a conditional verification (may not run)."""
    if _norm(getattr(call, "keyword", None)) in ("run keyword if", "run keyword unless"):
        return any("should" in _norm(a) for a in (getattr(call, "args", None) or ()))
    return False


def _try_blocks(node):
    """Yield native TRY blocks (RF 5+) anywhere in the test body."""
    for item in getattr(node, "body", None) or []:
        if type(item).__name__ == "Try" and _norm(getattr(item, "type", "")) == "try":
            yield item
        if hasattr(item, "body"):
            yield from _try_blocks(item)


def _except_swallows(try_node):
    """True if any EXCEPT branch of this TRY swallows the failure: its body has no
    Fail, no verification keyword, and no re-raise - only logging / no-op / empty."""
    branch = getattr(try_node, "next", None)
    while branch is not None:
        if _norm(getattr(branch, "type", "")) == "except":
            harmless = True
            for st in getattr(branch, "body", None) or []:
                if type(st).__name__ != "KeywordCall":
                    continue
                kw = _norm(st.keyword)
                if kw in ("fail", "fatal error") or "should" in kw or kw.startswith(VERIFY_PREFIXES):
                    harmless = False
                    break
            if harmless:
                return True
        branch = getattr(branch, "next", None)
    return False


def _try_body_has_keyword(try_node):
    return any(type(st).__name__ == "KeywordCall" for st in (getattr(try_node, "body", None) or []))


def _tags(testcase):
    tags = []
    for item in getattr(testcase, "body", None) or []:
        if type(item).__name__ == "Tags":
            tags += [str(v) for v in getattr(item, "values", []) or []]
    return tags


class Finding:
    __slots__ = ("file", "line", "test", "code", "detail", "level")

    def __init__(self, file, line, test, code, detail=""):
        self.file = file
        self.line = line
        self.test = test
        self.code = code
        self.detail = detail
        self.level = "unit"     # unit | integration | e2e; set per file in analyze_file

    def dict(self):
        title, conf, judg = CASES[self.code]
        return {"file": self.file, "line": self.line, "test": self.test,
                "code": self.code, "confidence": conf, "judgment": judg,
                "title": title, "detail": self.detail, "level": self.level,
                "fix": FIX_HINTS.get(self.code, "")}


def _name_implies_verification(name):
    """A user-keyword name that promises to verify. 'Check' is excluded - it often
    names a getter that returns a status for the caller to assert."""
    n = _norm(name)
    return "should" in n or n.startswith(("verify", "assert", "validate"))


def _call_level_smells(file, owner, calls, findings):
    """Per-call false-green checks shared by test cases, tasks, and user keywords:
    C5 (always-true), C7 (self-compare), C16 (Sleep). Returns whether any keyword
    call verifies something."""
    has_verification = False
    for c in calls:
        kw, args = c.keyword, list(getattr(c, "args", []) or [])
        ln = getattr(c, "lineno", 0) or 0
        # C23 runs first: a hard-coded IP URL can sit in the arguments of a
        # verification keyword (Should Be Equal ${url} http://10.0.0.5:8080),
        # and the assertion branches below `continue` before reaching it.
        for a in args:
            if _IP_URL_RE.search(a or ""):
                findings.append(Finding(file, ln, owner, "C23", "hard-coded IP-address URL"))
                break
        if _norm(kw) == "should be true" and args and _looks_constant_true(args[0]):
            findings.append(Finding(file, ln, owner, "C5", "Should Be True on a constant"))
            has_verification = True
            continue
        if _norm(kw) == "should be true" and len(args) == 1 and _is_bare_variable(args[0]):
            findings.append(Finding(file, ln, owner, "C6", "Should Be True on a bare variable (truthiness only)"))
            has_verification = True
            continue
        if _norm(kw) == "should be equal" and len(args) >= 2:
            if args[0] == args[1]:
                code = "C7" if args[0].startswith("${") else "C5"
                findings.append(Finding(file, ln, owner, code, "both sides are identical"))
            has_verification = True
            continue
        if _norm(kw) == "sleep":
            findings.append(Finding(file, ln, owner, "C16"))
        if is_verification(kw, args) or _rkif_verifies(c):
            has_verification = True
    return has_verification


def analyze_keyword(file, kw, findings):
    """Analyze a User Keyword definition (.robot Keywords section or .resource).
    Flags call-level smells inside the body, and R2 when the keyword is named like a
    verifier but verifies nothing (a hollow oracle used by tests)."""
    name = getattr(kw, "name", "") or ""
    line = getattr(kw, "lineno", 0) or 0
    calls = list(_keyword_calls(kw))

    # C2: empty keyword (only settings, no steps). A do-nothing keyword called
    # where verification should happen leaves the test green for free.
    if not _body_has_executable(kw):
        findings.append(Finding(file, line, name, "C2", "empty keyword"))
        return

    # R4: the only step(s) are No Operation — the keyword does nothing.
    if _only_no_operation(calls):
        findings.append(Finding(file, line, name, "R4"))
        return

    has_verification = _call_level_smells(file, name, calls, findings)
    if _name_implies_verification(name) and not has_verification:
        findings.append(Finding(file, line, name, "R2"))


def analyze_testcase(file, tc, findings):
    name = getattr(tc, "name", "") or ""
    line = getattr(tc, "lineno", 0) or 0
    calls = list(_keyword_calls(tc))
    tags = [_norm(t) for t in _tags(tc)]

    # C32: skipped
    if any("robot:skip" in t for t in tags) or any(_norm(c.keyword) in ("skip",) for c in calls):
        findings.append(Finding(file, line, name, "C32"))
        return

    # R5: a templated test ([Template] keyword) is driven by data rows. With no
    # data rows it generates zero cases and never runs. Templated tests carry
    # TemplateArguments, not keyword calls, so this is checked before the
    # call-based logic below.
    body_items = getattr(tc, "body", None) or []
    template = next((i for i in body_items if type(i).__name__ == "Template"), None)
    if template is not None:
        if not any(type(i).__name__ == "TemplateArguments" for i in body_items):
            findings.append(Finding(file, line, name, "R5"))
            return
        # Populated template: the [Template] keyword is the oracle for every data
        # row. When it is a known non-verifying builtin (e.g. [Template] Log), each
        # generated case runs without verifying anything - false-green (C2b).
        tmpl_kw = _norm(getattr(template, "value", None) or getattr(template, "name", None) or "")
        non_verifying = {"log", "log to console", "no operation", "sleep", "comment",
                         "set variable", "set test variable", "set suite variable",
                         "set global variable"}
        if tmpl_kw in non_verifying:
            findings.append(Finding(file, line, name, "C2b",
                                    "templated test's keyword does not verify anything"))
        return

    # R1: Pass Execution at the top level forces the test green regardless of checks
    if any(_norm(c.keyword) == "pass execution" for c in _top_level_keyword_calls(tc)):
        findings.append(Finding(file, line, name, "R1"))
        return

    # C2: empty (no keyword calls at all)
    if not calls:
        findings.append(Finding(file, line, name, "C2"))
        return

    # R4: the only step(s) are No Operation — the test runs but does nothing.
    if _only_no_operation(calls):
        findings.append(Finding(file, line, name, "R4"))
        return

    has_verification = _call_level_smells(file, name, calls, findings)

    # diagnostic/coupling group (off by default; emitted always, filtered in scan)
    if _has_control_block(tc):
        findings.append(Finding(file, line, name, "D2"))
    if len(calls) > DIAGNOSTIC_THRESHOLDS["long_test_steps"]:
        findings.append(Finding(file, line, name, "M2", "%d steps" % len(calls)))

    # C3: native TRY/EXCEPT whose EXCEPT swallows the failure
    for tb in _try_blocks(tc):
        if _try_body_has_keyword(tb) and _except_swallows(tb):
            findings.append(Finding(file, getattr(tb, "lineno", line), name, "C3",
                                    "TRY failure is swallowed by EXCEPT"))
            return

    # C3: swallow without an asserted status
    if not has_verification and any(is_swallow(c.keyword) for c in calls):
        findings.append(Finding(file, line, name, "C3"))
        return

    # C2b: keywords ran but nothing verified
    if not has_verification:
        findings.append(Finding(file, line, name, "C2b"))
        return

    # C21: a verification exists, but none runs unconditionally — the only
    # verification lives inside an IF/FOR block or a Run Keyword If. The guide is
    # explicit: no if/else/for at the test-case level.
    top = _top_level_keyword_calls(tc)
    has_unconditional = any(
        is_verification(c.keyword, list(getattr(c, "args", []) or []))
        for c in top
        if _norm(c.keyword) not in ("run keyword if", "run keyword unless")
    )
    if not has_unconditional and (_has_control_block(tc) or any(_rkif_verifies(c) for c in calls)):
        findings.append(Finding(file, line, name, "C21"))


def analyze_file(path):
    findings = []
    try:
        from robot.api import get_model
        from robot.parsing import ModelVisitor
    except Exception as exc:  # pragma: no cover
        sys.stderr.write("rffalsegreen: robotframework is required (%s)\n" % exc)
        return findings
    try:
        model = get_model(path)
    except Exception:
        return findings
    self_findings = findings
    is_resource = path.endswith(".resource")

    # R3: a .resource file holds keywords/variables for reuse; a *** Test Cases ***
    # section there is invalid and its cases never run. Flag the section once and
    # skip per-test analysis for the file (the keywords are still analyzed).
    if is_resource:
        for section in getattr(model, "sections", None) or []:
            if type(section).__name__ == "TestCaseSection":
                ln = getattr(getattr(section, "header", None), "lineno", 0) \
                    or getattr(section, "lineno", 0) or 1
                self_findings.append(Finding(path, ln, "", "R3",
                                             "Test Cases section is not allowed in a .resource file"))
                break

    class _V(ModelVisitor):
        def visit_TestCase(self, node):
            if not is_resource:
                analyze_testcase(path, node, self_findings)

        def visit_Task(self, node):  # RPA suites use *** Tasks ***, not *** Test Cases ***
            if not is_resource:
                analyze_testcase(path, node, self_findings)

        def visit_Keyword(self, node):  # user keyword defs in .robot Keywords + .resource
            analyze_keyword(path, node, self_findings)

    _V().visit(model)
    level = detect_pyramid_level(model)
    for f in findings:
        f.level = level
    return findings


# --- discovery + CLI -------------------------------------------------------
IGNORED_DIRS = {".git", ".tox", "venv", ".venv", "node_modules", "results", "output"}


def is_robot_file(path):
    return path.endswith((".robot", ".resource"))


def discover(paths):
    files = []
    for root in paths:
        if os.path.isfile(root):
            if is_robot_file(root):
                files.append(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
            for f in filenames:
                if is_robot_file(f):
                    files.append(os.path.join(dirpath, f))
    return sorted(set(files))


def _eff_conf(code):
    """Effective confidence: an off-by-default (D*/M*) code shows as 'low' when enabled."""
    c = CASES[code][1]
    return "low" if c == "off" else c


def scan(paths, disable=None, diagnostics=False, baseline=None):
    disable = disable or set()
    out = []
    for f in discover(paths):
        for finding in analyze_file(f):
            conf = CASES[finding.code][1]
            if finding.code in disable:
                continue
            if conf == "off" and not diagnostics:
                continue
            out.append(finding)
    if baseline:
        out = [a for a in out if fingerprint(a) not in baseline]
    return out


def _render_text(findings):
    if not findings:
        return "rffalsegreen: no false-positive patterns found."
    lines, high, low = [], 0, 0
    by_file = {}
    for f in findings:
        by_file.setdefault(f.file, []).append(f)
    for file, fs in by_file.items():
        lines.append("\n" + file)
        for f in sorted(fs, key=lambda x: x.line):
            title = CASES[f.code][0]
            conf = _eff_conf(f.code)
            tag = "HIGH" if conf == "high" else "low "
            high += conf == "high"
            low += conf == "low"
            lines.append("  %s %-4s L%-4d %s  %s" % (tag, f.code, f.line, f.test, title))
            if f.detail:
                lines.append("           " + f.detail)
            hint = FIX_HINTS.get(f.code, "")
            lines.append("           level: %s%s" % (
                f.level, ("   fix: " + hint) if hint else ""))
    lines.append("\n%d high, %d low. %s" % (high, low, TOOL_URI))

    # Test-pyramid breakdown + the most common fixes, over every finding shown.
    by_level, by_code = {}, {}
    for f in findings:
        by_level[f.level] = by_level.get(f.level, 0) + 1
        by_code[f.code] = by_code.get(f.code, 0) + 1
    order = ["unit", "integration", "e2e"]
    levels = [lv for lv in order if lv in by_level] + \
             [lv for lv in sorted(by_level) if lv not in order]
    lines.append("By level: " + ", ".join("%s:%d" % (lv, by_level[lv]) for lv in levels))
    top = sorted(by_code.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    lines.append("Top fixes:")
    for code, n in top:
        lines.append("  %s (%d): %s" % (code, n, FIX_HINTS.get(code, CASES[code][0])))
    return "\n".join(lines)


_OUTPUT_EXT = {"text": "txt", "json": "json", "sarif": "sarif", "junit": "xml"}


def _rel_uri(path):
    """A forward-slash relative URI (load-bearing for GitHub code scanning)."""
    try:
        rel = os.path.relpath(path)
    except ValueError:  # different drive on Windows
        rel = path
    return rel.replace("\\", "/")


def resolve_output_path(path, fmt):
    """Turn --output into a concrete file path. A directory (existing dir, a
    trailing separator, or an extension-less name like '.falsegreen') receives
    'report.<ext>' for the chosen format; anything else is treated as a file.
    Missing parent directories are created either way."""
    ext = _OUTPUT_EXT.get(fmt, "txt")
    base = os.path.basename(path.rstrip("/\\"))
    is_dir = (path.endswith(("/", "\\")) or os.path.isdir(path)
              or os.path.splitext(base)[1] == "")
    if is_dir:
        os.makedirs(path, exist_ok=True)
        return os.path.join(path, "report." + ext)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Output formats: JSON / SARIF / JUnit. Confidence maps to severity the same way
# in every format - HIGH is the blocker, LOW/INFO is a warning - so a finding
# reads the same whether GitHub code scanning (SARIF) or a CI test report
# (JUnit) consumes it. The JSON shape is unchanged (the tool/version/judgments
# envelope), so existing consumers keep working.
# ---------------------------------------------------------------------------
def render_json(findings):
    return json.dumps({"tool": "robotframework-falsegreen", "version": __version__,
                       "judgments": JUDGMENTS,
                       "findings": [f.dict() for f in findings]}, indent=2)


def _sarif_level(conf):
    if conf == "high":
        return "error"
    if conf == "low":
        return "warning"
    return "note"


def render_sarif(findings):
    """SARIF 2.1.0: HIGH -> error, LOW -> warning, off/info -> note (via the
    finding's effective confidence). Forward-slash relative URIs, one tool with a
    rule per emitted code. Each result tags its judgment family and pyramid level
    so GitHub code scanning can group and filter them."""
    codes = []
    for a in findings:
        if a.code not in codes:
            codes.append(a.code)
    rules = []
    for code in codes:
        title, default_conf, judgment = CASES[code]
        rules.append({
            "id": code,
            "name": code,
            "shortDescription": {"text": title},
            "defaultConfiguration": {"level": _sarif_level(_eff_conf(code))},
            "helpUri": TOOL_URI,
            "properties": {"tags": [judgment, "group:" + group_of(code)]},
        })
    results = []
    for a in findings:
        title, _, judgment = CASES[a.code]
        text = title + (" (%s)" % a.detail if a.detail else "")
        results.append({
            "ruleId": a.code,
            "level": _sarif_level(_eff_conf(a.code)),
            "message": {"text": text},
            "properties": {"tags": [judgment, "group:" + group_of(a.code),
                                    "level:" + a.level]},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": _rel_uri(a.file)},
                    "region": {"startLine": max(a.line, 1)},
                }
            }],
        })
    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "robotframework-falsegreen",
                "informationUri": TOOL_URI,
                "version": __version__,
                "rules": rules,
            }},
            "results": results,
        }],
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


def render_junit(findings):
    """JUnit XML: HIGH -> <failure>, LOW/INFO -> <skipped>. One testcase per
    finding, named with the code, file and line so a CI test report links back to
    the suite."""
    n = len(findings)
    n_high = sum(1 for a in findings if _eff_conf(a.code) == "high")
    n_non_high = n - n_high
    attrs = {"name": "robotframework-falsegreen", "tests": str(n),
             "failures": str(n_high), "skipped": str(n_non_high), "errors": "0"}
    suites = ET.Element("testsuites", attrs)
    suite = ET.SubElement(suites, "testsuite", attrs)
    for a in sorted(findings, key=lambda x: (x.file, x.line)):
        title = CASES[a.code][0] + (" (%s)" % a.detail if a.detail else "")
        case = ET.SubElement(suite, "testcase", {
            "classname": "robotframework-falsegreen.%s" % a.code,
            "name": "%s %s:%d" % (a.code, _rel_uri(a.file), a.line),
        })
        loc = "%s:%d" % (_rel_uri(a.file), a.line)
        if _eff_conf(a.code) == "high":
            el = ET.SubElement(case, "failure", {"message": title})
            el.text = loc
        else:
            ET.SubElement(case, "skipped", {"message": "%s  %s" % (title, loc)})
    xml = ET.tostring(suites, encoding="unicode")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + xml


# ---------------------------------------------------------------------------
# Baseline (ratchet): fingerprint by content, not line number. Adopt a tool on a
# suite that already has findings without a wall of red - record today's
# findings, then fail only on new ones. The fingerprint omits the line number so
# it survives unrelated edits that shift a test up or down the file.
# ---------------------------------------------------------------------------
def fingerprint(finding):
    """Stable id: sha1(relpath, code, test, detail)[:16]. No line number, so the
    fingerprint survives unrelated line shifts in the suite. The Robot Finding has
    no source snippet, so the test/keyword name is the content discriminator - it
    keeps two findings with the same code and detail in one file (e.g. two empty
    tests) from collapsing into one fingerprint."""
    key = "\0".join([
        _rel_uri(finding.file), finding.code,
        finding.test or "", finding.detail or "",
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def load_baseline(path):
    """Read a baseline file into a set of fingerprints (empty set if unreadable)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return set()
    return {item["fingerprint"] for item in data.get("findings", [])
            if isinstance(item, dict) and item.get("fingerprint")}


def write_baseline(path, findings):
    """Write all current findings as a baseline. Returns how many were recorded."""
    items = [{
        "fingerprint": fingerprint(a),
        "code": a.code,
        "file": _rel_uri(a.file),
        "test": a.test,
        "detail": a.detail,
    } for a in sorted(findings, key=lambda x: (x.file, x.line))]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "tool": "robotframework-falsegreen", "findings": items},
                  fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return len(items)


# ---------------------------------------------------------------------------
# Project-layer audit (--config-audit): the suite reports green by run config,
# not by a smell inside any one suite file. Reads the Robot run config.
# ---------------------------------------------------------------------------
def _read_toml_file(path):
    try:
        import tomllib as _t
    except Exception:
        try:
            import tomli as _t
        except Exception:
            return None
    try:
        with open(path, "rb") as fh:
            return _t.load(fh)
    except Exception:
        return None


def audit_config(start=None):
    """Project-layer audit: read the Robot run config (robot.toml, pyproject
    [tool.robot]/[tool.robotframework], *.args argument files) and report PL9 -
    a skip-on-failure / noncritical option that turns a failing test into a
    non-fatal pass. Findings carry the config file and level 'project'.
    Returns [] when no such config is found."""
    import glob
    base = start or os.getcwd()
    findings = []

    def _flag(path, detail=""):
        f = Finding(path, 1, "", "PL9", detail)
        f.level = "project"
        findings.append(f)

    toml_sources = (
        ("robot.toml", lambda d: d),
        ("pyproject.toml", lambda d: (d.get("tool", {}).get("robot")
                                      or d.get("tool", {}).get("robotframework") or {})),
    )
    for name, getter in toml_sources:
        path = os.path.join(base, name)
        if not os.path.isfile(path):
            continue
        data = _read_toml_file(path)
        if data is None:
            continue
        section = getter(data) or {}
        keys = {str(k).replace("-", "").replace("_", "").lower() for k in section}
        if {"skiponfailure", "noncritical"} & keys:
            _flag(path, "skip-on-failure/noncritical in %s" % name)
            return findings

    for argfile in sorted(glob.glob(os.path.join(base, "*.args"))):
        try:
            with open(argfile, "r", encoding="utf-8") as fh:
                text = fh.read()
        except Exception:
            continue
        if re.search(r"--(skiponfailure|noncritical)\b", text):
            _flag(argfile, "skip-on-failure/noncritical in argument file")
            return findings
    return findings


RENDERERS = {"text": _render_text, "json": render_json,
             "sarif": render_sarif, "junit": render_junit}


def _emit(rendered, output, fmt):
    """Write the rendered report to a file (resolving a directory to report.<ext>)
    or to stdout."""
    if output:
        dest = resolve_output_path(output, fmt)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(rendered + "\n")
    else:
        print(rendered)


def main(argv=None):
    p = argparse.ArgumentParser(prog="rffalsegreen",
                                description="Find false-positive Robot Framework tests (static).")
    p.add_argument("paths", nargs="*", default=["."], help="files or directories (default: cwd)")
    p.add_argument("--format", choices=["text", "json", "sarif", "junit"], default="text",
                   help="output format (default: text)")
    p.add_argument("--json", action="store_true", help="alias for --format json")
    p.add_argument("--output", default=None, metavar="PATH",
                   help="write the output to PATH instead of stdout; "
                        "a directory (e.g. .falsegreen/) gets report.<ext>")
    p.add_argument("--config-audit", action="store_true",
                   help="audit the Robot run config (robot.toml / argument files) for "
                        "project-layer false-green (PL codes) instead of scanning suites")
    p.add_argument("--disable", default="", help="comma-separated codes to turn off")
    p.add_argument("--diagnostics", action="store_true",
                   help="also report the opt-in maintainability group (D*/M*)")
    p.add_argument("--baseline", nargs="?", const=".falsegreen-baseline.json", default=None,
                   metavar="PATH",
                   help="suppress findings recorded in PATH (default .falsegreen-baseline.json); "
                        "fail only on findings not in the baseline")
    p.add_argument("--write-baseline", nargs="?", const=".falsegreen-baseline.json", default=None,
                   metavar="PATH",
                   help="record all current findings to PATH as a baseline, then exit 0")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)
    disable = {c.strip() for c in args.disable.split(",") if c.strip()}
    fmt = "json" if args.json else args.format

    if args.write_baseline is not None:
        findings = scan(args.paths or ["."], disable=disable, diagnostics=args.diagnostics)
        n = write_baseline(args.write_baseline, findings)
        sys.stderr.write("rffalsegreen: wrote %d fingerprint(s) to %s\n"
                         % (n, args.write_baseline))
        return 0

    if args.config_audit:
        base = next((d for d in (args.paths or ["."]) if os.path.isdir(d)), os.getcwd())
        findings = audit_config(base)
        _emit(RENDERERS[fmt](findings), args.output, fmt)
        return 10 if findings else 0

    baseline = load_baseline(args.baseline) if args.baseline else None
    findings = scan(args.paths or ["."], disable=disable, diagnostics=args.diagnostics,
                    baseline=baseline)
    _emit(RENDERERS[fmt](findings), args.output, fmt)
    if any(_eff_conf(f.code) == "high" for f in findings):
        return 20
    if findings:
        return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
