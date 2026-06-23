#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
falsegreen-robot: deterministic false-positive scanner for Robot Framework tests.

Parses .robot files with the official Robot Framework parser (robot.api.get_model)
- no execution - and flags test cases that pass green without protecting anything:
a test with no verification keyword, a swallowed Run Keyword And Ignore Error, an
always-true Should Be True ${TRUE}, a self-compare, Sleep used as a wait, a skipped
test. Sibling of falsegreen (Python/pytest) and falsegreen-js (JS/TS).

Output: readable text (default) or JSON (--json).
Exit: 0 clean, 10 low-confidence only, 20 high-confidence present.
"""
import argparse
import json
import os
import re
import sys

__version__ = "0.1.0"
TOOL_URI = "https://github.com/vinicq/falsegreen-robot"

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
}

# Default thresholds for the opt-in groups (overridable later via config).
DIAGNOSTIC_THRESHOLDS = {"long_test_steps": 10}


def group_of(code):
    """false-positive (C*/R*) / diagnostic (D*) / coupling (M*) — mirrors the siblings."""
    if code.startswith("D"):
        return "diagnostic"
    if code.startswith("M"):
        return "coupling"
    return "false-positive"

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
    __slots__ = ("file", "line", "test", "code", "detail")

    def __init__(self, file, line, test, code, detail=""):
        self.file = file
        self.line = line
        self.test = test
        self.code = code
        self.detail = detail

    def dict(self):
        title, conf, judg = CASES[self.code]
        return {"file": self.file, "line": self.line, "test": self.test,
                "code": self.code, "confidence": conf, "judgment": judg,
                "title": title, "detail": self.detail}


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
        for a in args:
            if _IP_URL_RE.search(a or ""):
                findings.append(Finding(file, ln, owner, "C23", "hard-coded IP-address URL"))
                break
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
    if any(type(i).__name__ == "Template" for i in body_items):
        if not any(type(i).__name__ == "TemplateArguments" for i in body_items):
            findings.append(Finding(file, line, name, "R5"))
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
        sys.stderr.write("falsegreen-robot: robotframework is required (%s)\n" % exc)
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


def scan(paths, disable=None, diagnostics=False):
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
    return out


def _render_text(findings):
    if not findings:
        return "falsegreen-robot: no false-positive patterns found."
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
    lines.append("\n%d high, %d low. %s" % (high, low, TOOL_URI))
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(prog="falsegreen-robot",
                                description="Find false-positive Robot Framework tests (static).")
    p.add_argument("paths", nargs="*", default=["."], help="files or directories (default: cwd)")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--disable", default="", help="comma-separated codes to turn off")
    p.add_argument("--diagnostics", action="store_true",
                   help="also report the opt-in maintainability group (D*/M*)")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)
    disable = {c.strip() for c in args.disable.split(",") if c.strip()}
    findings = scan(args.paths or ["."], disable=disable, diagnostics=args.diagnostics)
    if args.json:
        print(json.dumps({"tool": "falsegreen-robot", "version": __version__,
                          "judgments": JUDGMENTS,
                          "findings": [f.dict() for f in findings]}, indent=2))
    else:
        print(_render_text(findings))
    if any(_eff_conf(f.code) == "high" for f in findings):
        return 20
    if findings:
        return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
