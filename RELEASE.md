# Releasing robotframework-falsegreen

Publishing to PyPI uses Trusted Publishing (OIDC) through `.github/workflows/release.yml`.
No long-lived API token lives in the repo: the publish job proves its identity to PyPI
with a short-lived OIDC credential.

## One-time setup (before the first publish)

### 1. PyPI Trusted Publisher

On pypi.org, under the project's Publishing settings (or as a pending publisher for a name
that does not exist yet), add a GitHub trusted publisher for `robotframework-falsegreen`:

- GitHub owner: `vinicq`
- Repository: `robotframework-falsegreen`
- Workflow: `release.yml`
- Environment: `pypi`

A pending publisher lets the very first release claim the name through OIDC, with no manual
upload needed.

### 2. GitHub environment

Create a `pypi` environment in the repository settings so the publish job can reference it.
No secret is required when trusted publishing is configured.

## Publishing a version

1. Bump `__version__` in `src/falsegreen_robot/scanner.py` and `version` in
   `pyproject.toml` in lockstep.
2. Move the `[Unreleased]` entries in `CHANGELOG.md` under the new version with today's date.
3. Run the checks locally: `pytest -q`, `ruff check src tests`, and the self-scan
   `python -m falsegreen_robot src tests`. The self-scan must report no HIGH findings
   before tagging.
4. Commit: `git add -A && git commit -m "release: X.Y.Z"`.
5. Tag and push: `git tag -a vX.Y.Z -m "robotframework-falsegreen vX.Y.Z" && git push origin main --tags`.
6. Create the GitHub release: `gh release create vX.Y.Z --generate-notes`. Publishing the
   release fires `release.yml`, which builds the sdist and wheel and publishes to PyPI.

The workflow is idempotent: if the version is already on PyPI, the publish step skips
instead of failing.

Confirm it is live: <https://pypi.org/project/robotframework-falsegreen/>

## Version scheme

[Semantic Versioning](https://semver.org/spec/v2.0.0.html):
- **PATCH** (`0.x.Y`): bug fixes, false-positive fixes, docs.
- **MINOR** (`0.X.0`): new detection codes, new config options, backward-compatible features.
- **MAJOR** (`X.0.0`): breaking changes to the CLI, config format, or output structure.
