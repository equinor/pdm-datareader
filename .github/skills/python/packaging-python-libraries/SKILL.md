---
name: packaging-pdm-datareader
description: Package and publish the pdm-datareader library to PyPI using uv and the uv_build backend. Covers PEP 621 metadata, uv.lock maintenance, building sdist + wheel, validating with Twine, verifying wheel contents, and GitHub trusted publishing. Use when releasing a new version, building distributables, or troubleshooting packaging issues.
---

# Packaging pdm-datareader

This project uses **uv** with the `uv_build` backend. Run the commands from the
repository root. End users can continue to install released packages with
`pip install pdm-datareader`.

## pyproject.toml Essentials

Metadata uses PEP 621 in `[project]`; development dependencies use dependency
groups, and `uv.lock` records the resolved environment:

```toml
[project]
name = "pdm-datareader"
version = "2.5.5"
description = "A small python package to execute queries to PDM ..."
requires-python = ">=3.11,<4"
authors = [{ name = "PDM TEAM", email = "AWL@equinor.com" }]
license = "MIT"
readme = "README.md"
dependencies = [
    "msal-bearer>=1.6.1,<2.0.0",
    "PyJWT>=2.15.1,<3.0.0",
    "pyodbc>=5.1.0,<6",
    "pandas>=2.2.2,<4.0.0",
    "sqlalchemy>=2.0.36,<3",
    "urllib3>=2.8.0,<3",
]

[dependency-groups]
dev = ["pytest>=9.0.3,<10", "black>=26.10.1,<27"]

[tool.uv]
default-groups = "all"

[build-system]
requires = ["uv_build>=0.13.7,<0.14.0"]
build-backend = "uv_build"
```

- The package uses the `src/pdm_datareader/` layout.
- Runtime dependencies go under `[project].dependencies`; development tools
  (`pytest`, `black`) go under `[dependency-groups].dev` and are not shipped.

## Version Bump (do this every release)

Bump `version` under `[project]` following SemVer
(`MAJOR.MINOR.MICRO` — see the versioning section in
`.github/copilot-instructions.md`). Either edit the field directly or use:

```bash
# Update [project].version, then refresh the lockfile.
uv lock
```

## Building

```bash
uv build                     # creates sdist + wheel in dist/
```

## Validate Metadata

```bash
uv tool run --from twine twine check dist/*
```

## Verify the Built Artifact (a green build is not a correct wheel)

`uv build` succeeding only means the backend ran — not that the wheel
contains your code. Always inspect wheel contents before publishing:

```bash
python -m zipfile -l dist/*.whl
```

Confirm the wheel contains `pdm_datareader/__init__.py` and
`pdm_datareader/tools.py` — not just a top-level file. The source files live
under `src/pdm_datareader/`; `twine check` validates metadata, not contents, so
it won't catch a missing module.

Then prove it from a clean install, outside the repo root (so `import` doesn't
pick up the source tree):

```bash
uv venv /tmp/verify
uv pip install --python /tmp/verify/bin/python dist/*.whl
cd /tmp && /tmp/verify/bin/python -c "from pdm_datareader import tools; tools.query"
```

On Windows PowerShell:

```powershell
uv venv $env:TEMP\verify
uv pip install --python "$env:TEMP\verify\Scripts\python.exe" (Get-ChildItem dist\*.whl)
Push-Location $env:TEMP
& "$env:TEMP\verify\Scripts\python.exe" -c "from pdm_datareader import tools; tools.query"
Pop-Location
```

Assert on a real symbol (`tools.query`), never just that the top-level name
imports — a shadowing empty package can make a bare `import` succeed and prove
nothing.

## Publishing to PyPI

The GitHub Actions workflows publish with PyPI trusted publishing. The TestPyPI
workflow builds and publishes test distributions; a GitHub release triggers the
production workflow. Do not store PyPI tokens in the repository.

## Dependency Best Practices

```toml
# DO: bounded PEP 440 ranges
msal-bearer = ">=1.6.1,<2.0.0"
pyodbc = ">=5.1.0,<6"

# DON'T: exact pins that lock users to one release
pyodbc = "5.1.0"
```

After changing dependencies, run `uv lock` and commit the updated `uv.lock`.
Keep `requires-python` aligned with the supported versions (3.11–3.14).

## Checklist

```
Before Release:
- [ ] Version bumped under [project] (SemVer)
- [ ] README.md updated for any new feature
- [ ] `uv run pytest` passes and `uv run black .` leaves files unchanged
- [ ] `uv build` succeeds
- [ ] `uv tool run --from twine twine check dist/*` passes
- [ ] `unzip -l dist/*.whl` shows pdm_datareader/__init__.py + tools.py
- [ ] Installed the wheel into a clean venv and imported tools.query from
      a directory outside the repo
- [ ] TestPyPI workflow passes before production release

After Release:
- [ ] pip install pdm-datareader works
- [ ] from pdm_datareader import query works
- [ ] GitHub release / tag created
```
