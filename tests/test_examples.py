"""Verify the examples/ tree: every BAD case triggers its code, and the
look-alikes leave the CLEAN cases quiet.

Mirrors the Python sibling's approach (falsegreen/examples): scan each shipped
example file with the real analyzer and assert the expected codes are present.
analyze_file returns every finding, including the off-by-default diagnostic
group, so one pass covers default and opt-in codes. The robot scanner only reads
.robot/.resource files, so this .py test is never self-scanned.
"""
import os

import pytest

from falsegreen_robot.scanner import analyze_file, CASES

EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "examples")


def _codes(name):
    path = os.path.join(EXAMPLES_DIR, name)
    return {f.code for f in analyze_file(path)}


# Each example file maps to the codes its BAD cases must trigger. The CLEAN
# look-alikes share the file; only presence is required, so a CLEAN case that
# stays quiet does not weaken the check. Extra incidental codes (e.g. a D2 from a
# C21 IF block) are allowed: the assertion is a subset check.
EXPECTED = {
    "effectiveness.robot": {"C5", "C6", "C7", "C9", "C44", "R6", "R2"},
    "execution.robot": {
        "C2", "C2b", "C3", "C20", "C21", "C32", "CC", "R1", "R4", "R5", "R7",
    },
    "nondeterminism.robot": {"C16"},
    "dependency.robot": {"C23"},
    "templates.robot": {"C37"},
    "resource_file.resource": {"R3"},
    "diagnostics.robot": {"D2", "M2"},
}


@pytest.mark.parametrize("name,expected", sorted(EXPECTED.items()))
def test_example_triggers_expected_codes(name, expected):
    found = _codes(name)
    missing = sorted(expected - found)
    assert missing == [], "%s missing %s (found %s)" % (name, missing, sorted(found))


def test_every_emitted_code_has_an_example():
    """Drift guard: the union of the per-file codes, plus the config-audit-only
    PL series (which scans the Robot run config, not a .robot file), must cover
    every code in the catalog. A new code added to CASES without an example
    fails here."""
    covered = set().union(*EXPECTED.values())
    config_audit_only = {"PL9"}
    missing = sorted(c for c in CASES if c not in covered and c not in config_audit_only)
    assert missing == [], "catalog codes with no example: %s" % missing
