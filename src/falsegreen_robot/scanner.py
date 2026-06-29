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

__version__ = "0.6.0"  # keep in lockstep with pyproject.toml (test_version_lockstep enforces it)
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
    "C3":  ("Run Keyword And Ignore Error/Return Status, or a TRY/EXCEPT that swallows the failure, leaves the status never asserted", "high", "J1"),
    "C5":  ("always-true check (Should Be True ${TRUE} / Should Be Equal with equal literals, or a constant-true Set Variable If feeding the expected side)", "high", "J2"),
    "C6":  ("weak check — Should Be True on a bare variable (truthiness only, not a comparison)", "low", "J4"),
    "C7":  ("self-compare (Should Be Equal ${x} ${x})", "high", "J2"),
    "C9":  ("Run Keyword And Expect Error with a catch-all pattern (*, GLOB:*, or REGEXP:.* accepts any error)", "low", "J4"),
    "C20": ("verification after a [Return]/Return/Fail/Pass Execution in the same block — dead step that never runs", "high", "J1"),
    "C37": ("duplicate data row in a [Template] — the same scenario runs twice, adds no coverage", "low", "J4"),
    "CC":  ("commented-out verification keyword (# Should Be Equal ...) — the oracle is switched off", "low", "J1"),
    "C16": ("non-deterministic source: Sleep, a clock read (Get Current Date), or randomness (Generate Random String / Evaluate datetime|random|uuid)", "low", "J1"),
    "C23": ("hard-coded IP-address URL in test data (environment coupling / mystery guest)", "low", "J6"),
    "C21": ("verification only runs conditionally (inside IF / Run Keyword If) — it may never execute", "low", "J1"),
    "C32": ("skipped test (robot:skip / Skip) never runs", "low", "J1"),
    "C31": ("captured value never used (${x}= Get Text loc) - the test verifies something else, so the capture is dead", "low", "J4"),
    "R1":  ("Pass Execution forces the test to pass regardless of any check (forced green)", "high", "J1"),
    "R2":  ("user keyword named like a verifier (Verify/Assert/Should...) but its body contains no verification — a hollow oracle", "low", "J1"),
    "R3":  ("*** Test Cases *** section inside a .resource file — invalid; the cases never run", "high", "J1"),
    "R4":  ("No Operation is the only step — the test/task/keyword does nothing", "high", "J1"),
    "R5":  ("[Template] with no data rows — the templated test is generated with zero cases", "high", "J1"),
    "R6":  ("Should Be True on a string literal (not an expression) — a non-empty string is always truthy, so it never fails", "low", "J4"),
    "R7":  ("templated test whose in-file [Template] keyword contains no verification — every generated case runs without an oracle", "low", "J1"),
    "R8":  ("the only verification lives in [Setup]/Test Setup — it checks preconditions BEFORE the body acts, so the body can break and the suite stays green", "high", "J1"),
    "R8b": ("the only verification lives in [Teardown]/Test Teardown — it runs even when the body fails and reports on a separate axis", "low", "J1"),
    "C9b": ("RequestsLibrary HTTP method with expected_status=any/anything — the request accepts every status, so the oracle is disabled (a 500 never fails)", "low", "J1"),
    "C11a": ("self-confirming literal: the expected value is a copy of the actual (${y}= Set Variable ${x}, then Should Be Equal ${x} ${y}) — the oracle confirms itself", "high", "J2"),
    "C44": ("library assertion provably true for any value (Should Contain ${EMPTY}, Should Not Be Empty ${TRUE}, Length Should Be tautology)", "high", "J2"),
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
    "C9":  "match the specific error message/pattern, not a catch-all",
    "C16": "wait for the condition (Wait Until...) instead of Sleep",
    "C20": "move the verification before the [Return]/Fail so it runs",
    "C37": "remove the duplicate [Template] data row",
    "CC":  "restore the commented-out verification keyword, or delete the line",
    "C21": "move the verification out of the IF/Run Keyword If so it always runs",
    "C23": "read the URL from a variable/resource, not a hard-coded IP",
    "C32": "remove the skip, or document why with a reason",
    "C31": "assert the captured value, or drop the assignment if it is unused",
    "R1":  "remove Pass Execution; let the checks decide the result",
    "R2":  "make the verifier keyword actually assert, or rename it",
    "R3":  "move the test cases to a .robot suite; .resource holds keywords only",
    "R4":  "replace No Operation with real steps and a verification",
    "R5":  "add data rows to the [Template], or remove the template",
    "R6":  "pass a real expression (${x} > 0), not a bare string literal",
    "R7":  "add a verification keyword to the [Template] keyword, or template a verifier",
    "R8":  "move the verification into the test body so it runs after the SUT acts",
    "R8b": "verify in the body, not only in [Teardown]; teardown runs on a separate axis",
    "C9b": "set expected_status to the specific code/name, not any/anything",
    "C11a": "compare against an independent expected value, not a copy of the actual",
    "C44": "assert a meaningful value, not one always satisfied",
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
# RequestsLibrary HTTP method keywords (with or without the " On Session" form).
# A request carrying expected_status=<specific code/name> asserts the status: the
# call fails when the response status differs, so it is a real oracle.
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
# expected_status values that DISABLE the check (no oracle): the request accepts any outcome.
_EXPECTED_STATUS_OFF = {"any", "anything"}
SWALLOW_KEYWORDS = {"run keyword and ignore error", "run keyword and return status"}
# Keywords that UNCONDITIONALLY end the current block: nothing after them in the
# same body runs. A test case cannot use [Return], so the test-level terminators
# are the keywords that always stop execution (Fail aborts, Pass Execution
# short-circuits to green, Return From Keyword exits a user keyword). The `...If`
# variants (Pass Execution If, Return From Keyword If) and Run Keyword If are
# CONDITIONAL - a verification after them runs when the guard is false, so they
# do NOT terminate the block. [Return]/ReturnSetting is handled separately
# because it is a setting node, not a KeywordCall.
TERMINATOR_KEYWORDS = {"fail", "fatal error", "pass execution",
                       "return from keyword"}
CONDITIONAL_TERMINATOR_KEYWORDS = {"pass execution if", "return from keyword if"}
# Guard values that Robot always evaluates as true, so a `...If` terminator with
# this guard never lets the following step run (the rest of the block is dead).
_CONST_TRUE_GUARDS = {"true", "${true}", "1"}
# Run Keyword And Expect Error patterns that accept ANY error: a bare glob star,
# or a GLOB form whose pattern is just star(s). Only the glob matcher reads `*` as
# a wildcard - a bare pattern is glob by default. EQUALS:* / STARTS:* match the
# LITERAL string "*" (a specific message), and REGEXP:* is an invalid regex, so
# none of those is a catch-all. Matching any error makes the oracle vacuous - it
# never tells a real failure from a typo.
_CATCH_ALL_ERROR_RE = re.compile(r"^(?:GLOB:\s*)?\*+$", re.IGNORECASE)
# The regex form of the same vacuous oracle: REGEXP: followed by a pattern that
# matches every message (`.*`, `.+`, lazy `.*?`, with optional anchors/parens),
# e.g. `REGEXP:.*` or `REGEXP:^.*$`. A bare `.*` is NOT this: without REGEXP: it is
# glob, where `.` is literal, so it only matches messages starting with a dot.
_CATCH_ALL_REGEXP_RE = re.compile(r"^REGEXP:\s*\^?\(?\.[*+]\??\)?\$?$", re.IGNORECASE)


def _norm(name):
    return (name or "").strip().lower()


def _strip_library_prefix(keyword, local_keywords=None):
    """Drop a leading library/resource prefix from a keyword call. Robot allows
    `LibraryName.Keyword Name` (and aliases, e.g. `api.GET On Session`); the prefix
    is the text before the LAST `.` of the first token, because keyword base names do
    not contain `.` while library/resource prefixes do. `RequestsLibrary.GET` -> `GET`,
    `BuiltIn.Should Be Equal` -> `Should Be Equal`. Only strips when there is a `.` and
    a non-empty keyword remains after it; otherwise returns the name unchanged.

    A keyword defined IN THIS FILE takes priority over an imported library: Robot
    resolves a local keyword before a resource/library one. So when the full name is a
    locally-defined keyword (`local_keywords`, normalized), the dotted name is the real
    keyword (e.g. an in-file `api.GET`), not a `LibraryName.Keyword`, and must NOT be
    stripped - otherwise `api.GET` would be misread as RequestsLibrary's `GET`."""
    if not keyword:
        return keyword
    if local_keywords and _norm(keyword) in local_keywords:
        return keyword
    first, sep, rest = keyword.partition(" ")
    if "." in first:
        base = first.rsplit(".", 1)[1]
        if base:
            return base + sep + rest
    return keyword


def is_verification(keyword, args, local_keywords=None, extra_verify=None):
    """True if this keyword call verifies an expected result (is an oracle)."""
    if keyword is None:
        return False
    keyword = _strip_library_prefix(keyword, local_keywords)
    n = _norm(keyword)
    # Config-declared custom verifiers (#54): match the FULL normalized keyword name
    # against the user substrings, so `Expect Response Ok` matches `expect response`.
    # Anchored to the whole name, not a split leaf (no L1 leaf-match). Opt-in: an
    # empty set leaves behavior byte-identical, and this only ever SUPPRESSES a
    # false positive, never creates a finding.
    if extra_verify and any(pat in n for pat in extra_verify):
        return True
    if "should" in n:
        return True                              # BuiltIn/Collections/String/Selenium/...
    if n == "run keyword and expect error":
        return True                              # asserts a failure occurs (the error is the oracle)
    if keyword in REST_SCHEMA:
        return True                              # RESTinstance schema assertions
    if n.startswith(VERIFY_PREFIXES):
        return True                              # custom Verify*/Assert*/Validate*/Check *
    if n.startswith("wait until") and any(w in n for w in ("contain", "visible", "present")):
        return True                              # Selenium/Appium waits that fail on timeout
    # Wait Until Keyword Succeeds  <retry>  <interval>  <keyword>  *args - a retry
    # wrapper. It is an oracle only if the wrapped keyword is one: retrying an
    # assertion (Should Be Equal) is verification; retrying a bare action (Click) is
    # not. Skip the two retry-config args, then resolve the inner keyword and recurse.
    if n == "wait until keyword succeeds":
        inner = list(args or ())[2:]
        if inner:
            return is_verification(inner[0], inner[1:], local_keywords, extra_verify)
        return False
    if n.startswith("get ") and any(a in BROWSER_OPS for a in (args or ())):
        return True                              # Browser assertion engine: Get ... == expected
    # RequestsLibrary: GET/POST/... (optionally "On Session") with a specific
    # expected_status asserts the response status. expected_status=any/anything
    # disables it, so that form is NOT an oracle.
    if n.replace(" on session", "") in HTTP_METHODS:
        for a in args or ():
            key, sep, val = (a or "").partition("=")
            if sep and _norm(key) == "expected_status":
                return _norm(val) not in _EXPECTED_STATUS_OFF and bool(val.strip())
    # Run Keyword And Continue On Failure / And Warn On Failure    <kw>    *args -
    # the soft-assert wrappers: the wrapped keyword still runs and is verified, the
    # wrapper only changes how a failure is reported (continue / warn). It is an
    # oracle exactly when the wrapped keyword is one, so recurse on the inner call.
    if n in ("run keyword and continue on failure", "run keyword and warn on failure"):
        inner = list(args or ())
        if inner:
            return is_verification(inner[0], inner[1:], local_keywords, extra_verify)
        return False
    # Run Keywords    A    AND    B    AND    Should Be Equal ... — a chain that
    # runs each keyword in sequence. The verification can be any segment, so split
    # on the AND separator and check each segment's first token as a nested call.
    if n == "run keywords":
        for seg_kw, seg_args in _run_keywords_segments(args):
            if is_verification(seg_kw, seg_args, local_keywords, extra_verify):
                return True
    return False


def _run_keywords_segments(args):
    """Yield `(keyword_name, [keyword_args])` for each nested call in a `Run Keywords`
    argument list. Robot runs `Run Keywords` two ways:

    - WITH literal `AND` separators: each `AND`-delimited segment is one call, its
      first token the keyword name and the rest its arguments. `GET    url
      expected_status=200    AND    Log    done` ->
      `('GET', ['url', 'expected_status=200'])`, `('Log', ['done'])`.
    - WITHOUT any `AND`: Robot runs EACH argument as its own no-arg keyword. `Open
      Page    Verify Page Loaded` -> `('Open Page', [])`, `('Verify Page Loaded', [])`.

    So the verification can be any segment, with its own arguments (the RequestsLibrary
    expected_status / Browser `Get ... ==` logic needs them)."""
    args = list(args or ())
    if not any(_norm(a) == "and" for a in args):
        for a in args:
            yield a, []
        return
    segment = []
    for a in args:
        if _norm(a) == "and":
            if segment:
                yield segment[0], segment[1:]
            segment = []
        else:
            segment.append(a)
    if segment:
        yield segment[0], segment[1:]


def is_swallow(keyword):
    return _norm(keyword) in SWALLOW_KEYWORDS


_VAR_NAME_RE = re.compile(r"[\$@&]\{([^{}]+)\}")


def _assigned_names(call):
    """Bare variable names assigned by a KeywordCall, lower-cased without the
    ${}/decoration or trailing '='. `${status}    ${value}=` -> {'status', 'value'}."""
    names = set()
    for tok in getattr(call, "assign", None) or ():
        m = _VAR_NAME_RE.search(tok or "")
        if m:
            names.add(_norm(m.group(1)))
    return names


def _referenced_names(call):
    """Variable names referenced in a KeywordCall's keyword text and arguments,
    lower-cased and bare. Used to tell whether a swallowed status is ever read."""
    names = set()
    fields = [getattr(call, "keyword", "") or ""]
    fields += [a or "" for a in (getattr(call, "args", None) or ())]
    for field in fields:
        for m in _VAR_NAME_RE.finditer(field):
            names.add(_norm(m.group(1)))
    return names


def _control_condition_names(node):
    """Variable names read by the condition/header of every IF/WHILE in the body
    (recursing into nested blocks), lower-cased and bare. `IF ${status}` /
    `WHILE not ${status}` consume the status in the block HEADER, not in a
    KeywordCall - so a status read only there must still count as used (C3)."""
    names = set()
    for item in getattr(node, "body", None) or []:
        cond = getattr(item, "condition", None)
        if cond:
            for m in _VAR_NAME_RE.finditer(cond):
                names.add(_norm(m.group(1)))
        if hasattr(item, "body"):
            names |= _control_condition_names(item)
    return names


def _swallow_status_unused(calls, node=None):
    """C3 (status form): a Run Keyword And Ignore Error / Return Status whose first
    assigned variable (the status) is never referenced by a later keyword call.
    Returns the lineno of the offending swallow, or None.

    `${status}=    Run Keyword And Return Status    ...` followed by no use of
    ${status} is the Robot try/except/pass - the failure is captured and dropped.

    A status consumed only by a control-block condition (`IF ${status}` /
    `WHILE not ${status}` - the idiomatic Robot conditional) is read in the block
    HEADER, never in a KeywordCall, so the body node is walked for condition
    variables and those count as a use too (#78)."""
    condition_names = _control_condition_names(node) if node is not None else set()
    swallows = []
    for idx, c in enumerate(calls):
        if type(c).__name__ != "KeywordCall" or not is_swallow(c.keyword):
            continue
        assigned = list(getattr(c, "assign", None) or ())
        if not assigned:
            continue                       # result discarded entirely - the bare-call C3 path
        status = _assigned_names(c)
        if not status:
            continue
        used_later = any(status & _referenced_names(later) for later in calls[idx + 1:])
        if not used_later and not (status & condition_names):
            swallows.append(getattr(c, "lineno", 0) or 0)
    return swallows[0] if swallows else None


def _expected_names(call):
    """Variable names referenced in the EXPECTED slot of a Should Be Equal call -
    its second positional argument (`Should Be Equal    ${actual}    ${expected}`),
    lower-cased and bare. Named args (key=value) are skipped so the slot stays
    positional."""
    positional = [a for a in (getattr(call, "args", None) or ())
                  if "=" not in (a or "").split("}")[0]]
    if len(positional) < 2:
        return set()
    names = set()
    for m in _VAR_NAME_RE.finditer(positional[1] or ""):
        names.add(_norm(m.group(1)))
    return names


def _set_variable_if_pins_oracle(calls):
    """C5 (#47): a `Set Variable If` with a constant-true guard (first arg in
    _CONST_TRUE_GUARDS) whose assigned variable flows into the EXPECTED side of a
    later `Should Be Equal`. The oracle is then pinned to a constant the test fixed,
    so the assertion is tautological. Yields the lineno of each such Set Variable If.

    Both conditions are required: (1) the guard is a literal constant-true, AND (2)
    the assigned name actually reaches an assertion's expected argument. A runtime
    variable guard is normal branching and stays silent; if the flow cannot be
    proven (the name never lands on an expected slot), stay silent."""
    for idx, c in enumerate(calls):
        if type(c).__name__ != "KeywordCall" or _norm(getattr(c, "keyword", "")) != "set variable if":
            continue
        guard = next(iter(getattr(c, "args", None) or ()), "")
        if _norm(guard) not in _CONST_TRUE_GUARDS:
            continue
        assigned = _assigned_names(c)
        if not assigned:
            continue
        for later in calls[idx + 1:]:
            if type(later).__name__ != "KeywordCall" or _norm(getattr(later, "keyword", "")) != "should be equal":
                continue
            if assigned & _expected_names(later):
                yield getattr(c, "lineno", 0) or 0
                break


_EMPTY_STR_LITERALS = {"${empty}", '""', "''", ""}


def _is_empty_literal(arg):
    """True for an argument Robot evaluates to the empty string: ${EMPTY}, a literal
    "" / '' , or a blank cell. Not a variable that merely could be empty at runtime."""
    return _norm(arg) in _EMPTY_STR_LITERALS


def _is_nonempty_literal(arg):
    """True for a non-empty plain literal (no variable, has text) - or a constant-true
    guard (${TRUE}/true/1), which is never empty either. Used by C44 form 2."""
    s = (arg or "").strip()
    if not s:
        return False
    if _norm(s) in _CONST_TRUE_GUARDS:
        return True
    return "{" not in s and "}" not in s


def _vacuous_library_assertion(calls):
    """C44 (#53): a library assertion provably true for ANY runtime value. Yields the
    lineno of each high-precision vacuous form:

    1. Should Contain    ${x}    ${EMPTY}   - every string contains the empty string.
    2. Should Not Be Empty    ${TRUE}       - a non-empty literal / constant is never empty.
    3. Should Be Empty    ${EMPTY}          - the empty literal is always empty.
    4. Length Should Be    ${EMPTY}    0, OR a Length Should Be whose subject was
       assigned by an immediately-preceding literal Set Variable (no intervening
       reassignment) and whose expected equals that literal's length.

    Excluded (FP ceiling): two free variables, a runtime-computed length, and
    Should Be True ${EMPTY} (that is R6/C6, handled elsewhere). The dead-line
    discipline (suppress where C5/C6/R6 already own the line) is applied by the caller."""
    for idx, c in enumerate(calls):
        if type(c).__name__ != "KeywordCall":
            continue
        kw = _norm(getattr(c, "keyword", ""))
        args = list(getattr(c, "args", None) or [])
        ln = getattr(c, "lineno", 0) or 0
        if kw == "should contain" and len(args) >= 2 and _is_empty_literal(args[1]):
            yield ln
        elif kw == "should not be empty" and len(args) >= 1 and _is_nonempty_literal(args[0]):
            yield ln
        elif kw == "should be empty" and len(args) >= 1 and _is_empty_literal(args[0]):
            yield ln
        elif kw == "length should be" and len(args) >= 2:
            subject, expected = args[0], args[1]
            if _is_empty_literal(subject) and expected.strip() == "0":
                yield ln
                continue
            # Subject assigned by an immediately-preceding literal Set Variable, with
            # no intervening reassignment, and expected == that literal's length.
            subj_names = {_norm(m.group(1)) for m in _VAR_NAME_RE.finditer(subject or "")}
            if len(subj_names) != 1 or idx == 0:
                continue
            prev = calls[idx - 1]
            if (type(prev).__name__ == "KeywordCall"
                    and _norm(getattr(prev, "keyword", "")) == "set variable"):
                prev_assigned = _assigned_names(prev)
                prev_args = list(getattr(prev, "args", None) or [])
                # literal value only: one arg, no variable in it (a keyword-call or
                # Set Variable If would not be a Set Variable; a variable value is runtime)
                if (subj_names <= prev_assigned and len(prev_args) == 1
                        and "{" not in (prev_args[0] or "") and "}" not in (prev_args[0] or "")):
                    try:
                        if expected.strip() == str(len(prev_args[0])):
                            yield ln
                    except (TypeError, ValueError):
                        pass


def _expected_status_off_value(args):
    """Return the disabled expected_status value ('any'/'anything') if an HTTP-method
    call carries `expected_status=any|anything`, else None. Reuses the exact-match set
    `_EXPECTED_STATUS_OFF` (a specific code/name stays an oracle, never flagged)."""
    for a in args or ():
        key, sep, val = (a or "").partition("=")
        if sep and _norm(key) == "expected_status" and _norm(val) in _EXPECTED_STATUS_OFF:
            return _norm(val)
    return None


def _status_asserted_later(calls, idx, resp_names):
    """True when a later `Should*` call asserts the status of a response assigned at
    `calls[idx]` (#78). The author disabled the request-level oracle with
    `expected_status=any` on purpose, then checks the status manually on the next
    line - `Should Be Equal As Integers    ${resp.status_code}    200` or the
    `${resp}[status_code]` item form. Matched against the response's assigned name
    (`resp_names`), so an unrelated status assert does not suppress C9b."""
    if not resp_names:
        return False
    for later in calls[idx + 1:]:
        if type(later).__name__ != "KeywordCall":
            continue
        if "should" not in _norm(getattr(later, "keyword", "")):
            continue
        for a in getattr(later, "args", None) or ():
            low = _norm(a)
            if "status_code" not in low:
                continue
            # ${resp.status_code} (attribute) or ${resp}[status_code] (item access).
            for name in resp_names:
                if ("${%s.status_code}" % name) in low or ("${%s}[status_code]" % name) in low:
                    return True
    return False


def _captured_value_unused(calls, source_lines, scope_end):
    """C31 (#34): a keyword call that captures a value (`${x}=    Get Text    loc`)
    whose captured name is never referenced afterwards, while the test verifies
    something else. The capture is dead - the call ran for its return value, but the
    value is dropped. Yields the lineno of each such capture.

    Precision-first, deferred and shipped at LOW on purpose. Guards (per #34):

    - Skip `Set Variable*` assignments (Set Variable / Set Test|Suite|Global Variable
      and Set Variable If). Those name a variable to be read by a LATER step that the
      author may write outside this scan, and the no-oracle / pinned-oracle cases are
      already C2b / C5 / C11a.
    - Skip swallow captures (Run Keyword And Ignore Error / Return Status): the unused
      STATUS form is C3, owned there.
    - A capture counts as USED when its bare name appears as a token anywhere later
      WITHIN THE SAME TEST (up to scope_end, the test's end_lineno - so a later
      keyword call, an `IF`/`WHILE` condition, a `Log ${x}`, an `Evaluate` that
      splices it, or the `[Teardown]` all count). Bounded to the test on purpose: a
      same-named variable in a LATER test must not keep this capture alive (L5). The
      scan is otherwise broad - any in-test textual mention suppresses, so the only
      thing flagged is a capture with no downstream mention in its own test.
    - Only fires when the test still verifies something else (the caller gates this on
      has_verification). A capture in a test with no oracle is C2b, not C31.
    """
    for c in calls:
        if type(c).__name__ != "KeywordCall":
            continue
        kw = _norm(getattr(c, "keyword", ""))
        if kw.startswith("set variable") or kw.startswith("set test variable") \
                or kw.startswith("set suite variable") or kw.startswith("set global variable"):
            continue
        if is_swallow(c.keyword):
            continue
        assigned = _assigned_names(c)
        if not assigned:
            continue
        ln = getattr(c, "lineno", 0) or 0
        # Every variable token mentioned on a later physical source line, up to the
        # owning test's end (covers Log / Evaluate strings / teardown / continuations,
        # but not a later test that happens to reuse the name).
        used_tokens = set()
        for later in source_lines[ln:scope_end]:
            for m in _VAR_NAME_RE.finditer(later):
                used_tokens.add(_norm(m.group(1)))
        if not (assigned & used_tokens):
            yield ln


def _self_confirming_literal(calls):
    """C11a (#76): a self-confirming literal. `${y}=    Set Variable    ${x}` copies the
    actual into a new variable, then `Should Be Equal    ${x}    ${y}` (either order)
    compares the value against its own copy - the oracle confirms itself. Yields the
    lineno of each such Should Be Equal.

    High-precision corner only: the expected side must be a PURE copy made in-body by a
    Set Variable of a single bare variable (no transform, no Evaluate, no literal). A
    transform (Evaluate, a computed value) may carry real meaning and is left alone; the
    plain `${x}    ${x}` form is already C7. FP bound: both names must resolve to the same
    source variable through one Set Variable copy, with no intervening reassignment of the
    copy."""
    # Map: copy-variable name -> source-variable name, from `${y}= Set Variable ${x}`.
    # Built in line order; a later reassignment of EITHER the copy or its source drops the
    # entry, so a snapshot-then-recompute (`${y}=Set Variable ${x}` ... `${x}=Recompute`)
    # is no longer a self-confirming compare.
    copies = {}
    for c in calls:
        if type(c).__name__ != "KeywordCall":
            continue
        is_copy = _norm(getattr(c, "keyword", "")) == "set variable"
        cargs = list(getattr(c, "args", None) or [])
        assigned = _assigned_names(c)
        new_copy = None
        if is_copy and len(assigned) == 1 and len(cargs) == 1 and _is_bare_variable(cargs[0]):
            src = {_norm(m.group(1)) for m in _VAR_NAME_RE.finditer(cargs[0])}
            if len(src) == 1:
                new_copy = (next(iter(assigned)), next(iter(src)))
        # Any reassignment invalidates a copy keyed on or sourced from that name, EXCEPT the
        # Set Variable that creates the copy we are about to record.
        for name in assigned:
            for k in [k for k, v in copies.items() if k == name or v == name]:
                if not (new_copy and k == new_copy[0]):
                    del copies[k]
        if new_copy is not None:
            copies[new_copy[0]] = new_copy[1]
        if _norm(getattr(c, "keyword", "")) == "should be equal":
            args = [a for a in (getattr(c, "args", None) or [])
                    if "=" not in (a or "").split("}")[0]]
            if len(args) < 2 or not (_is_bare_variable(args[0]) and _is_bare_variable(args[1])):
                continue
            a0 = next(iter(_VAR_NAME_RE.finditer(args[0])), None)
            a1 = next(iter(_VAR_NAME_RE.finditer(args[1])), None)
            if not (a0 and a1):
                continue
            n0, n1 = _norm(a0.group(1)), _norm(a1.group(1))
            # one side is a copy of the other (in either operand position)
            if copies.get(n0) == n1 or copies.get(n1) == n0:
                yield getattr(c, "lineno", 0) or 0


def _looks_constant_true(arg):
    return _norm(arg) in ("${true}", "true", "1", "${1}")


_BARE_VAR_RE = re.compile(r"^[\$@&]\{[^{}]+\}$")
# A URL whose host is a literal IP address: strong signal of environment coupling
# (the test points at a fixed machine). A hostname URL is too common in E2E to flag.
_IP_URL_RE = re.compile(r"https?://\d{1,3}(?:\.\d{1,3}){3}\b")
# An `Evaluate` body that reaches for the clock or randomness (module access, so a
# variable like `random_seed` is not matched): datetime./random./uuid. (C16).
# Ceiling: keys on the `module.` substring, so it would also match the same text inside
# a string literal (`Evaluate    'datetime.now'`) — implausible in practice, accepted.
_EVAL_NONDET_RE = re.compile(r"\b(?:datetime|random|uuid)\.")
# Body item types that actually do something (vs. settings like [Documentation]).
_EXECUTABLE_TYPES = {"KeywordCall", "If", "For", "While", "Try", "Var",
                     "ReturnStatement", "Return", "TemplateArguments"}


def _is_bare_variable(arg):
    """True for a lone variable like ${x} (no comparison/expression) — a weak oracle
    when passed to Should Be True (truthiness only)."""
    return bool(_BARE_VAR_RE.match((arg or "").strip()))


# Operators that turn a Should Be True argument into a real boolean expression.
# Robot evaluates the argument as Python, so any of these means the author wrote
# a comparison or call - not a bare literal that is always truthy.
_EXPR_TOKENS = ("==", "!=", "<", ">", "<=", ">=", " and ", " or ", " not ",
                " in ", " is ", "(", "+", "-", "*", "/", "%")


# Literals that Robot evaluates to a FALSY Python value: Should Be True on one of
# these CAN fail, so it is a real (if odd) oracle, not the always-true R6 smell.
_FALSY_LITERALS = {"0", "0.0", "false", "none", '""', "''"}


def _is_string_literal_truthy(arg):
    """True for a Should Be True argument that is a non-empty string LITERAL with no
    expression operators and no variable - it is always truthy, so the check can
    never fail (RF17). A bare ${x} is C6 (truthiness), not this; an expression like
    `${n} > 0` is a real oracle and not flagged; a falsy literal (0/False/None) can
    fail and is not flagged either."""
    s = (arg or "").strip()
    if not s:
        return False
    if "{" in s and "}" in s:          # contains a variable - not a plain literal
        return False
    if any(tok in s for tok in _EXPR_TOKENS):
        return False                   # real expression (comparison, call, boolean)
    if _norm(s) in _FALSY_LITERALS:
        return False                   # falsy literal: the check can still fail
    return True                        # plain non-empty truthy text: always truthy


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


def _rkif_verifies(call, extra_verify=None):
    """A `Run Keyword If`/`Unless` whose arguments name a verification keyword -
    that is a conditional verification (may not run)."""
    if _norm(getattr(call, "keyword", None)) in ("run keyword if", "run keyword unless"):
        for a in (getattr(call, "args", None) or ()):
            na = _norm(a)
            if "should" in na or (extra_verify and any(p in na for p in extra_verify)):
                return True
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


def _dead_verification_after_terminator(node, local_keywords=None, extra_verify=None):
    """Yield (lineno) for each verification keyword that sits AFTER a terminator in
    the same body block - a [Return]/Return statement, or a Fail/Pass Execution/
    Return From Keyword call. Nothing after the terminator runs, so a check there is
    dead (C20). Each block body is scanned on its own so a terminator inside an IF
    branch does not orphan a sibling at the parent level."""
    body = getattr(node, "body", None) or []
    terminated = False
    for item in body:
        cls = type(item).__name__
        if terminated and cls == "KeywordCall" and is_verification(
                item.keyword, list(getattr(item, "args", []) or []), local_keywords, extra_verify):
            yield getattr(item, "lineno", 0) or 0
        # A setting [Return]/ReturnSetting or a Return statement ends the block.
        if cls in ("ReturnSetting", "Return", "ReturnStatement"):
            terminated = True
        elif cls == "KeywordCall" and _norm(item.keyword) in TERMINATOR_KEYWORDS:
            terminated = True
        elif cls == "KeywordCall" and _norm(item.keyword) in CONDITIONAL_TERMINATOR_KEYWORDS:
            guard = next(iter(getattr(item, "args", []) or []), "")
            if _norm(guard) in _CONST_TRUE_GUARDS:
                terminated = True
        # Recurse into control blocks (their own bodies are scanned independently).
        if hasattr(item, "body") and cls in ("If", "For", "While", "Try"):
            yield from _dead_verification_after_terminator(item, local_keywords, extra_verify)


def _duplicate_template_rows(testcase):
    """Yield the lineno of each [Template] data row that repeats an earlier row's
    argument tuple (C37). Identical rows drive the templated keyword with the same
    inputs twice - the second adds no coverage."""
    seen = set()
    for item in getattr(testcase, "body", None) or []:
        if type(item).__name__ != "TemplateArguments":
            continue
        key = tuple(getattr(item, "args", None) or ())
        if key in seen:
            yield getattr(item, "lineno", 0) or 0
        else:
            seen.add(key)


def _suite_fixture_keywords(model):
    """The suite-level Test Setup / Test Teardown keyword calls from *** Settings ***,
    as {'setup': (keyword, args) or None, 'teardown': (keyword, args) or None}. These
    apply to every test in the file that does not override them with its own [Setup]/
    [Teardown]. Suite Setup/Suite Teardown run once per suite, not per test, so they are
    out of scope for a per-test oracle-phase check."""
    out = {"setup": None, "teardown": None}
    for section in getattr(model, "sections", None) or []:
        for item in getattr(section, "body", None) or []:
            cls = type(item).__name__
            kw = getattr(item, "name", None)
            args = list(getattr(item, "args", None) or [])
            if cls == "TestSetup" and kw:
                out["setup"] = (kw, args)
            elif cls == "TestTeardown" and kw:
                out["teardown"] = (kw, args)
    return out


# Sentinel: the test explicitly set [Setup]/[Teardown] NONE, which CLEARS the inherited
# suite fixture (distinct from "the test has no [Setup]", which inherits it).
_NONE_FIXTURE = object()


def _test_fixture_keywords(testcase):
    """The test's own [Setup]/[Teardown] as {'setup', 'teardown'}, distinguishing three
    states per slot: None (the test has no such setting, so it inherits the suite fixture),
    _NONE_FIXTURE (an explicit `[Setup] NONE` that clears the inherited fixture), or a
    (keyword, args) tuple (an own fixture)."""
    out = {"setup": None, "teardown": None}
    for item in getattr(testcase, "body", None) or []:
        cls = type(item).__name__
        kw = getattr(item, "name", None)
        args = list(getattr(item, "args", None) or [])
        slot = "setup" if cls == "Setup" else "teardown" if cls == "Teardown" else None
        if slot is None:
            continue
        if not kw or _norm(kw) == "none":
            out[slot] = _NONE_FIXTURE      # explicit NONE (or empty): clears the inherited fixture
        else:
            out[slot] = (kw, args)
    return out


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


def _call_level_smells(file, owner, calls, findings, local_keywords=None, extra_verify=None):
    """Per-call false-green checks shared by test cases, tasks, and user keywords:
    C5 (always-true), C7 (self-compare), C16 (Sleep). Returns whether any keyword
    call verifies something."""
    has_verification = False
    # C5 (#47): a constant-true Set Variable If whose assigned value feeds the
    # expected side of a later Should Be Equal pins the oracle to a fixed constant.
    for svi_ln in _set_variable_if_pins_oracle(calls):
        findings.append(Finding(file, svi_ln, owner, "C5",
                                "Set Variable If with a constant-true guard pins the expected value"))
    for c_idx, c in enumerate(calls):
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
        if _norm(kw) == "should be true" and args and _is_string_literal_truthy(args[0]):
            findings.append(Finding(file, ln, owner, "R6",
                                    "Should Be True on a string literal (always truthy)"))
            has_verification = True
            continue
        if _norm(kw) == "run keyword and expect error" and args \
                and (_CATCH_ALL_ERROR_RE.match((args[0] or "").strip())
                     or _CATCH_ALL_REGEXP_RE.match((args[0] or "").strip())):
            findings.append(Finding(file, ln, owner, "C9", "expects any error (catch-all pattern)"))
            has_verification = True
            continue
        # C9b (#75): a RequestsLibrary HTTP method with expected_status=any/anything is an
        # assertion-shaped call with its oracle switched off - the request accepts every
        # status. Distinct from C2b ('no oracle'): here the oracle exists but is disabled.
        # Reuses the exact-match _EXPECTED_STATUS_OFF set is_verification already keys on.
        if _norm(_strip_library_prefix(kw, local_keywords)).replace(" on session", "") in HTTP_METHODS:
            off = _expected_status_off_value(args)
            if off is not None:
                # Suppress when the body asserts this response's status manually right
                # after (the author disabled the request oracle on purpose) - #78.
                if not _status_asserted_later(calls, c_idx, _assigned_names(c)):
                    findings.append(Finding(file, ln, owner, "C9b",
                                            "expected_status=%s accepts any HTTP status" % off))
                has_verification = True
                continue
        if _norm(kw) == "should be equal" and len(args) >= 2:
            if args[0] == args[1]:
                code = "C7" if args[0].startswith("${") else "C5"
                findings.append(Finding(file, ln, owner, code, "both sides are identical"))
            has_verification = True
            continue
        # Strip a library prefix so the idiomatic DateTime.Get Current Date /
        # String.Generate Random String / BuiltIn.Sleep forms still match (#63).
        nk = _norm(_strip_library_prefix(kw, local_keywords))
        if nk == "sleep":
            findings.append(Finding(file, ln, owner, "C16"))
        elif nk == "get current date":
            findings.append(Finding(file, ln, owner, "C16", "Get Current Date reads the clock (non-deterministic)"))
        elif nk == "generate random string":
            findings.append(Finding(file, ln, owner, "C16", "Generate Random String is non-deterministic (no fixed seed)"))
        elif nk == "evaluate" and args and _EVAL_NONDET_RE.search(args[0] or ""):
            findings.append(Finding(file, ln, owner, "C16", "Evaluate body uses datetime/random/uuid (non-deterministic)"))
        if is_verification(kw, args, local_keywords, extra_verify) or _rkif_verifies(c, extra_verify):
            has_verification = True
    # C44 (#53): a library assertion provably true for any runtime value. Suppress
    # where C5/C6/R6 already own the line (the dead-line discipline) - those codes
    # take precedence on the same assertion. A C44 form is itself a verification.
    owned = {f.line for f in findings if f.code in ("C5", "C6", "R6")}
    for c44_ln in _vacuous_library_assertion(calls):
        if c44_ln not in owned:
            findings.append(Finding(file, c44_ln, owner, "C44",
                                    "assertion is satisfied for any value"))
        has_verification = True
    # C11a (#76): a Should Be Equal whose expected side is an in-body copy of the actual
    # (made by a Set Variable). The assertion confirms itself - a verification, but a
    # circular one. Suppress where C7 already owns the line (the plain ${x} ${x} form).
    c7_owned = {f.line for f in findings if f.code == "C7"}
    for c11_ln in _self_confirming_literal(calls):
        if c11_ln not in c7_owned:
            findings.append(Finding(file, c11_ln, owner, "C11a",
                                    "expected value is a copy of the actual"))
        has_verification = True
    return has_verification


def analyze_keyword(file, kw, findings, local_keywords=None, extra_verify=None):
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

    has_verification = _call_level_smells(file, name, calls, findings, local_keywords, extra_verify)

    # C20: a verification after a [Return]/Return/Fail/Return From Keyword in the
    # same block is dead - it never runs.
    for dead_ln in _dead_verification_after_terminator(kw, local_keywords, extra_verify):
        findings.append(Finding(file, dead_ln, name, "C20",
                                "verification after a terminator never runs"))

    # C3 (status form): a swallow whose status the keyword body never reads.
    status_ln = _swallow_status_unused(calls, kw)
    if status_ln is not None:
        findings.append(Finding(file, status_ln, name, "C3",
                                "swallowed status is never asserted"))

    if _name_implies_verification(name) and not has_verification:
        findings.append(Finding(file, line, name, "R2"))


def _keyword_body_verifies(kw, local_keywords=None, extra_verify=None):
    """True if a user keyword definition's body contains any verification keyword.
    Runs the shared call-level scan over the body and discards its findings - only
    the has_verification verdict matters here (used by R7)."""
    calls = list(_keyword_calls(kw))
    return _call_level_smells("", "", calls, [], local_keywords, extra_verify)


def analyze_testcase(file, tc, findings, keyword_index=None, extra_verify=None, long_test=None, suite_fixtures=None, source_lines=None):
    name = getattr(tc, "name", "") or ""
    line = getattr(tc, "lineno", 0) or 0
    calls = list(_keyword_calls(tc))
    tags = [_norm(t) for t in _tags(tc)]
    # In-file keyword names (normalized) take priority over imported libraries, so a
    # dotted local keyword (api.GET) must not be prefix-stripped into a library call.
    local_keywords = set(keyword_index) if keyword_index else None

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
        # R7: the [Template] keyword is a USER keyword defined in this same file
        # whose body contains no verification. Every generated case then runs
        # without an oracle. FP bound: only flag when the keyword resolves in-file -
        # an external/imported template keyword may verify via something the scanner
        # cannot see, so stay silent. Skip when it is already a non-verifying builtin
        # (covered by C2b above) or when the keyword is named like a verifier (R2
        # already flags the hollow oracle on the definition).
        elif keyword_index is not None and tmpl_kw in keyword_index:
            kw_def = keyword_index[tmpl_kw]
            if (not _keyword_body_verifies(kw_def, local_keywords, extra_verify)
                    and not _name_implies_verification(getattr(kw_def, "name", "") or "")):
                findings.append(Finding(file, line, name, "R7",
                                        "in-file [Template] keyword verifies nothing"))
        # C37: a data row that repeats an earlier row runs the same scenario twice.
        for dup_ln in _duplicate_template_rows(tc):
            findings.append(Finding(file, dup_ln, name, "C37", "duplicate [Template] data row"))
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

    has_verification = _call_level_smells(file, name, calls, findings, local_keywords, extra_verify)

    # diagnostic/coupling group (off by default; emitted always, filtered in scan)
    if _has_control_block(tc):
        findings.append(Finding(file, line, name, "D2"))
    long_test_steps = long_test if long_test is not None else DIAGNOSTIC_THRESHOLDS["long_test_steps"]
    if len(calls) > long_test_steps:
        findings.append(Finding(file, line, name, "M2", "%d steps" % len(calls)))

    # C20: a verification keyword after a terminator ([Return]/Fail/Pass Execution/
    # Return From Keyword) in the same block is a dead step - it never runs.
    for dead_ln in _dead_verification_after_terminator(tc, local_keywords, extra_verify):
        findings.append(Finding(file, dead_ln, name, "C20",
                                "verification after a terminator never runs"))

    # C31 (#34): a captured value (${x}= Get Text loc) that no later step reads,
    # while the test still verifies something else. Deferred and shipped LOW,
    # precision-first: any later textual mention of the name (Log, an Evaluate
    # string, a teardown) counts as used, so only a wholly dead capture is flagged.
    # Gated on has_verification - a capture in a no-oracle test is C2b, not C31.
    if has_verification and source_lines is not None:
        scope_end = getattr(tc, "end_lineno", None) or len(source_lines)
        for cap_ln in _captured_value_unused(calls, source_lines, scope_end):
            findings.append(Finding(file, cap_ln, name, "C31",
                                    "captured value is never used"))

    # C3: native TRY/EXCEPT whose EXCEPT swallows the failure
    for tb in _try_blocks(tc):
        if _try_body_has_keyword(tb) and _except_swallows(tb):
            findings.append(Finding(file, getattr(tb, "lineno", line), name, "C3",
                                    "TRY failure is swallowed by EXCEPT"))
            return

    # C3 (status form): the swallow assigns a status that no later step reads. The
    # failure is captured and dropped - the Robot try/except/pass - even when the
    # test verifies something else, so this is checked before the no-oracle paths.
    status_ln = _swallow_status_unused(calls, tc)
    if status_ln is not None:
        findings.append(Finding(file, status_ln, name, "C3",
                                "swallowed status is never asserted"))
        return

    # C3: a swallow whose result is DISCARDED ENTIRELY (no assignment). A swallow
    # WITH an assigned status is fully handled by the status-form check above - it
    # fires there when the status is unused and stays silent when a later step or a
    # control-block header reads it (#78), so it must not be re-flagged here.
    if not has_verification and any(
            is_swallow(c.keyword) and not (getattr(c, "assign", None) or ())
            for c in calls):
        findings.append(Finding(file, line, name, "C3"))
        return

    # R8 (#74): the body runs keywords but does not verify - yet a fixture does. The
    # test's own [Setup]/[Teardown] takes priority over the suite-level Test Setup/
    # Teardown it would otherwise inherit. A verifying [Setup] checks preconditions
    # BEFORE the body acts (the body can break and the suite stays green) - high. A
    # verifying [Teardown]-only runs even on body failure, reporting on a separate
    # axis - low. Reuses is_verification, so custom/--verify-keywords still suppress.
    # Only fires on zero body verification (this branch); a body oracle pre-empts it.
    if not has_verification:
        fx = dict(suite_fixtures or {"setup": None, "teardown": None})
        own = _test_fixture_keywords(tc)
        if own["setup"] is not None:
            fx["setup"] = None if own["setup"] is _NONE_FIXTURE else own["setup"]
        if own["teardown"] is not None:
            fx["teardown"] = None if own["teardown"] is _NONE_FIXTURE else own["teardown"]
        setup_verifies = bool(fx["setup"]) and is_verification(
            fx["setup"][0], fx["setup"][1], local_keywords, extra_verify)
        teardown_verifies = bool(fx["teardown"]) and is_verification(
            fx["teardown"][0], fx["teardown"][1], local_keywords, extra_verify)
        if setup_verifies:
            findings.append(Finding(file, line, name, "R8",
                                    "verification only in [Setup]/Test Setup, not the body"))
            return
        if teardown_verifies:
            findings.append(Finding(file, line, name, "R8b",
                                    "verification only in [Teardown]/Test Teardown, not the body"))
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
        is_verification(c.keyword, list(getattr(c, "args", []) or []), local_keywords, extra_verify)
        for c in top
        if _norm(c.keyword) not in ("run keyword if", "run keyword unless")
    )
    if not has_unconditional and (_has_control_block(tc) or any(_rkif_verifies(c, extra_verify) for c in calls)):
        findings.append(Finding(file, line, name, "C21"))


# CC: a verification keyword that has been commented out. The Robot parser drops
# comments, so this is a raw source scan: a comment line (#) whose text begins with
# a Should*/Page Should*/...Should Be* keyword or a Verify*/Assert* call. The oracle
# was switched off but the line stays for show.
# The verification word must start the comment, or follow one or two capitalized
# prefix words (a library/object name like `Page Should Contain`, `Element Should
# Be Visible`). Requiring capitalized prefixes keeps prose out: `# this should
# work` does not match (lower-case `this`), but `# Should Be Equal ...` does.
_CC_RE = re.compile(
    r"""^\s*\#\s*
        (?:\.{3}\s*)?                       # a Robot line-continuation comment
        (?:[A-Z][A-Za-z0-9]*\ ){0,2}        # 0-2 capitalized prefix words (Page, Element)
        (?:Should|Verify|Assert|Validate)   # the verification verb
        (?:\ [A-Z][A-Za-z0-9]*)*            # 0+ more capitalized words: rest of the keyword name
        (?:\s{2,}|\t|\ ?[$@&]\{|\s*$)       # then a call shape: 2+space/tab arg sep, a ${/@{/&{ var, or EOL
    """,
    re.VERBOSE,
)


def _commented_out_verifications(source):
    """Yield linenos of comment lines that look like a switched-off verification
    keyword (CC). Matches `# Should Be Equal ...`, `# Page Should Contain ...`,
    `# Verify Login`. A plain prose comment (# TODO, # setup) does not match."""
    for i, line in enumerate(source.splitlines(), start=1):
        if _CC_RE.match(line):
            yield i


# Inline suppression: `# falsegreen: ignore` silences every code on that line,
# `# falsegreen: ignore[C16,C20]` silences only the listed ones. Same token and
# bracket syntax as falsegreen (Python) and falsegreen-js, so a maintainer learns
# one form across the ecosystem. Only the exact `falsegreen:` token suppresses.
IGNORE_RE = re.compile(r"#\s*falsegreen:\s*ignore(?:\[([A-Za-z0-9, ]+)\])?")


def parse_inline_ignores(source):
    """Map line number -> set of codes to suppress on that line, or {'*'} for all.
    Codes are upper-cased so `ignore[c16]` matches the `C16` a finding carries (#62).
    A suppression on a continuation (`...`) row is also folded onto the owning
    statement's first physical line, where the finding is actually reported (#64)."""
    lines = source.splitlines()
    ignores = {}

    def add(ln, codeset):
        ignores.setdefault(ln, set()).update(codeset)

    for i, line in enumerate(lines, start=1):
        m = IGNORE_RE.search(line)
        if not m:
            continue
        codes = m.group(1)
        codeset = {c.strip().upper() for c in codes.split(",") if c.strip()} if codes else {"*"}
        add(i, codeset)
        if line.lstrip().startswith("..."):
            # Walk back over preceding continuation rows to the statement that owns them.
            k = i - 2  # 0-based index of the line above
            while k >= 0 and lines[k].lstrip().startswith("..."):
                k -= 1
            if k >= 0:
                add(k + 1, codeset)
    return ignores


def analyze_file(path, extra_verify=None, long_test=None):
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

    # Pre-pass: index user keyword definitions in this file by normalized name, so a
    # [Template] keyword can be resolved to its in-file body (R7). Templates may
    # reference a keyword defined later in the file, so the index is built before any
    # test case is analyzed.
    keyword_index = {}

    class _KwIndex(ModelVisitor):
        def visit_Keyword(self, node):
            nm = _norm(getattr(node, "name", "") or "")
            if nm and nm not in keyword_index:
                keyword_index[nm] = node

    _KwIndex().visit(model)
    # Normalized names of every keyword defined in this file: a local keyword wins
    # over an imported library, so these names are not prefix-stripped.
    local_keywords = set(keyword_index) if keyword_index else None

    # Suite-level Test Setup/Teardown apply to every test that does not override them
    # with its own [Setup]/[Teardown] (R8). Collected once per file.
    suite_fixtures = _suite_fixture_keywords(model)

    # Raw source, read once: the parser drops comments (CC needs them) and the line
    # text is the broad "captured value used anywhere later" signal (C31, #34).
    try:
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
    except Exception:
        source = ""
    source_lines = source.splitlines()

    class _V(ModelVisitor):
        def visit_TestCase(self, node):
            if not is_resource:
                analyze_testcase(path, node, self_findings, keyword_index, extra_verify, long_test, suite_fixtures, source_lines)

        def visit_Task(self, node):  # RPA suites use *** Tasks ***, not *** Test Cases ***
            if not is_resource:
                analyze_testcase(path, node, self_findings, keyword_index, extra_verify, long_test, suite_fixtures, source_lines)

        def visit_Keyword(self, node):  # user keyword defs in .robot Keywords + .resource
            analyze_keyword(path, node, self_findings, local_keywords, extra_verify)

    _V().visit(model)

    # CC: commented-out verification keyword. Raw source scan (the parser drops
    # comments) - reuses the source read above. The test/keyword name is unknown at
    # the line level, so the finding carries the empty owner, like R3.
    for cc_ln in _commented_out_verifications(source):
        self_findings.append(Finding(path, cc_ln, "", "CC", "commented-out verification keyword"))

    # Inline suppression: drop a finding when its line carries a matching
    # `# falsegreen: ignore` (all codes) or `ignore[CODE,...]` (that code).
    ignores = parse_inline_ignores(source)
    if ignores:
        findings = [f for f in findings
                    if not (ignores.get(f.line) and ("*" in ignores[f.line] or f.code in ignores[f.line]))]

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


def scan(paths, disable=None, diagnostics=False, baseline=None, extra_verify=None, long_test=None):
    disable = disable or set()
    out = []
    for f in discover(paths):
        for finding in analyze_file(f, extra_verify, long_test):
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


_OUTPUT_EXT = {"text": "txt", "json": "json", "sarif": "sarif", "junit": "xml", "robot": "txt"}


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


# Project config file (#50): [tool.falsegreen] in pyproject.toml, else the whole
# .falsegreen.toml root table. First found wins (no merge). Distinct from
# --config-audit, which reads the Robot RUN config ([tool.robot]). Only these
# four keys are honored; CLI flags override/extend.
_CONFIG_KEYS = {"disable", "diagnostics", "long_test", "verify_keywords"}


def load_project_config(start=None):
    """Read tool config from `[tool.falsegreen]` in pyproject.toml, or the whole-file
    root table of `.falsegreen.toml`. First found wins (no merge). Returns a dict with
    `disable` (set of codes), `diagnostics` (bool), `long_test` (int or None) and
    `verify_keywords` (list of str). Unknown keys / codes warn to stderr (warn, not
    fail). Returns the empty-default dict when no file is found or TOML is unreadable."""
    base = start or os.getcwd()
    out = {"disable": set(), "diagnostics": False, "long_test": None, "verify_keywords": []}
    section = None
    pyproject = os.path.join(base, "pyproject.toml")
    if os.path.isfile(pyproject):
        data = _read_toml_file(pyproject)
        if data is not None:
            tool_fg = data.get("tool", {}).get("falsegreen")
            if isinstance(tool_fg, dict):
                section = tool_fg
    if section is None:
        dotfile = os.path.join(base, ".falsegreen.toml")
        if os.path.isfile(dotfile):
            data = _read_toml_file(dotfile)
            if isinstance(data, dict):
                section = data
    if section is None:
        return out

    for key in section:
        if key not in _CONFIG_KEYS:
            sys.stderr.write("rffalsegreen: unknown config key '%s'\n" % key)
    disable = section.get("disable")
    if isinstance(disable, list):
        for code in disable:
            if code in CASES:
                out["disable"].add(code)
            else:
                sys.stderr.write("rffalsegreen: unknown code '%s'\n" % code)
    if isinstance(section.get("diagnostics"), bool):
        out["diagnostics"] = section["diagnostics"]
    long_test = section.get("long_test")
    if isinstance(long_test, int) and not isinstance(long_test, bool):
        out["long_test"] = long_test
    verify = section.get("verify_keywords")
    if isinstance(verify, list):
        out["verify_keywords"] = [str(v) for v in verify]
    return out


def _discover_argfiles(base):
    """Yield every `*.args` under base, recursively, skipping IGNORED_DIRS (the same
    set file discovery uses, so .git/.venv/results/output/... are not scanned). A
    nested `tests/sub/run.args` is read; an artifact `results/x.args` is not.

    ponytail: settings in a suite-init `__init__.robot` are out of scope - the
    PL9 audit reads the run CONFIG layer (robot.toml / *.args), not suite source.
    A `__init__.robot` carrying skip metadata is a suite-source concern the
    per-file scan would own; parsing it here would mix the two layers. Documented,
    not half-built."""
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for f in filenames:
            if f.endswith(".args"):
                yield os.path.join(dirpath, f)


def audit_config(start=None):
    """Project-layer audit: read the Robot run config (robot.toml, pyproject
    [tool.robot]/[tool.robotframework], *.args argument files - walked recursively,
    skipping IGNORED_DIRS) and report PL9 - a skip-on-failure / noncritical option
    that turns a failing test into a non-fatal pass. Findings carry the config file
    and level 'project'. Returns [] when no such config is found.

    Suite-init (`__init__.robot`) settings are out of scope on purpose: this audits
    the run-config layer, not suite source. See _discover_argfiles."""
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

    for argfile in sorted(_discover_argfiles(base)):
        try:
            with open(argfile, "r", encoding="utf-8") as fh:
                text = fh.read()
        except Exception:
            continue
        if re.search(r"--(skiponfailure|noncritical)\b", text):
            _flag(argfile, "skip-on-failure/noncritical in argument file")
            return findings
    return findings


def render_robot(findings):
    """Per-test report (#8): findings grouped by suite file, then by the test case
    that owns them, the way a Robot Framework user reads log.html - "which of my
    test cases is a false green, and why". Each test heading is followed by its
    findings (code, confidence, line, title, fix); findings with no owning test
    (CC / R3, which sit at the file level, and the project-layer PL codes) are
    grouped under a `[suite-level]` heading so nothing is dropped.

    ponytail: this is the light track of #8. The heavy track - a Listener v3 /
    prerebotmodifier that injects findings into a real output.xml so they surface
    inside Robot's own log.html - is deliberately NOT built: the output.xml schema
    drifts across RF 4/5/7, and a finding in a .resource keyword has no owning test
    to attach to. This text grouping delivers "smells under each test" with none of
    that fragility. Add the listener if a user asks for in-log.html rendering.
    """
    if not findings:
        return "rffalsegreen: no false-positive patterns found."
    lines, high, low = [], 0, 0
    by_file = {}
    for f in findings:
        by_file.setdefault(f.file, []).append(f)
    for file in sorted(by_file):
        lines.append("\n" + file)
        by_test = {}
        for f in by_file[file]:
            by_test.setdefault(f.test or "", []).append(f)
        # Named tests first (alpha), then the file-level bucket last.
        named = sorted(t for t in by_test if t)
        order = named + ([""] if "" in by_test else [])
        for test in order:
            heading = test if test else "[suite-level]"
            lines.append("  %s" % heading)
            for f in sorted(by_test[test], key=lambda x: x.line):
                conf = _eff_conf(f.code)
                tag = "HIGH" if conf == "high" else "low "
                high += conf == "high"
                low += conf == "low"
                title = CASES[f.code][0]
                lines.append("    %s %-4s L%-4d %s" % (tag, f.code, f.line, title))
                if f.detail:
                    lines.append("           %s" % f.detail)
                hint = FIX_HINTS.get(f.code, "")
                if hint:
                    lines.append("           fix: %s" % hint)
    lines.append("\n%d high, %d low. %s" % (high, low, TOOL_URI))
    return "\n".join(lines)


RENDERERS = {"text": _render_text, "json": render_json,
             "sarif": render_sarif, "junit": render_junit, "robot": render_robot}


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
    p.add_argument("--format", choices=["text", "json", "sarif", "junit", "robot"], default="text",
                   help="output format (default: text); robot groups findings per test case")
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
    fmt = "json" if args.json else args.format

    # Project config file (#50): [tool.falsegreen] / .falsegreen.toml. CLI flags
    # override/extend - disable is additive, diagnostics is OR, long_test/verify
    # come from the file. Distinct from --config-audit (the Robot RUN config).
    cfg_base = next((d for d in (args.paths or ["."]) if os.path.isdir(d)), os.getcwd())
    cfg = load_project_config(cfg_base)
    disable = {c.strip() for c in args.disable.split(",") if c.strip()} | cfg["disable"]
    diagnostics = args.diagnostics or cfg["diagnostics"]
    long_test = cfg["long_test"]
    extra_verify = {_norm(v) for v in cfg["verify_keywords"] if _norm(v)} or None

    if args.write_baseline is not None:
        findings = scan(args.paths or ["."], disable=disable, diagnostics=diagnostics,
                        extra_verify=extra_verify, long_test=long_test)
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
    findings = scan(args.paths or ["."], disable=disable, diagnostics=diagnostics,
                    baseline=baseline, extra_verify=extra_verify, long_test=long_test)
    _emit(RENDERERS[fmt](findings), args.output, fmt)
    if any(_eff_conf(f.code) == "high" for f in findings):
        return 20
    if findings:
        return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
