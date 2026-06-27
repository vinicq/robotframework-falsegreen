# Status

Public product state of `robotframework-falsegreen` at a glance. For the full code catalog
and usage, see the [README](README.md); for the change history, see the [CHANGELOG](CHANGELOG.md).

Research artifacts, datasets, and unpublished numbers live in the private research hub,
never in this repo. This file tracks the public product only.

## Version

- Current: **0.3.0** (PyPI: `pip install robotframework-falsegreen`, command `rffalsegreen`)
- Versioning: semver; releases via trusted publishing (OIDC).

## CI health

- `ci.yml`: ruff plus pytest on Python 3.9 / 3.11 / 3.13.
- `release.yml`: PyPI publish on tag.
- `codex-review-gate.yml`, `release-drafter.yml`, `credit-contributor.yml`.

## Catalog coverage

Deterministic scan over the official Robot Framework parser (`robot.api`). Active codes:

- **Shared with falsegreen (same concept, same id):** C2, C2b, C3, C5, C6, C7, C9, C16,
  C20, C21, C23, C32, C37, CC.
- **Robot-specific:** R1, R2, R3, R4, R5, R6, R7.
- **Diagnostic (opt-in):** D2.
- **Coupling (opt-in):** M2.
- **Project layer (`--config-audit`):** PL9 (via `robot.toml` / args).

Each code carries a judgment tag (J1-J6) and a risk family (F1-F8); see the README catalog
and the docs site for what each one flags, with a BAD plus CLEAN example.

## Supported libraries

The `Should` convention plus library-specific assertion forms: SeleniumLibrary, Browser,
RESTinstance / RequestsLibrary, DatabaseLibrary, and custom keyword libraries.

## Scope

Static layer only. Statically provable false-green with a low false-positive rate. Semantic
judgment goes to `falsegreen-skill`; runtime and culture are out of scope by design.
