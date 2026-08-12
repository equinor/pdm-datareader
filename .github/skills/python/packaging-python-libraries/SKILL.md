---
name: packaging-pdm-datareader
description: Package and publish the pdm-datareader library to PyPI using Poetry and the poetry-core build backend. Covers pyproject.toml metadata, version bumps, building sdist + wheel, validating with twine, verifying wheel contents, and publishing. Use when releasing a new version, building distributables, or troubleshooting packaging issues.
---

# Packaging pdm-datareader

This project uses **Poetry** with the `poetry-core` build backend (see
`pyproject.toml`), not setuptools/hatchling/uv. Commands below assume Poetry is
installed and you are at the repo root.

## pyproject.toml Essentials

Metadata lives under `[tool.poetry]`:

```toml
[tool.poetry]
name = "pdm-datareader"
version = "2.5.5"
description = "A small python package to execute queries to PDM ..."
authors = ["PDM TEAM <AWL@equinor.com>"]
license = "MIT"
readme = "README.md"
packages = [{ include = "pdm_datareader" }]
repository = "https://github.com/equinor/pdm-datareader"

[tool.poetry.dependencies]
python = "^3.11"
msal-bearer = ">=1.3.0,<2.0.0"
pyodbc = "^5.1.0"
pandas = ">=2.2.2,<4.0.0"
sqlalchemy = "^2.0.36"
urllib3 = "^2.3.0"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

- `packages = [{ include = "pdm_datareader" }]` tells poetry-core which package
  directory to ship — keep it in sync with the actual package folder.
- Runtime deps go under `[tool.poetry.dependencies]`; dev-only tools
  (`pytest`, `black`) go under `[tool.poetry.group.dev.dependencies]` and are
  **not** shipped to users.

## Version Bump (do this every release)

Bump `version` under `[tool.poetry]` following SemVer
(`MAJOR.MINOR.MICRO` — see the versioning section in
`.github/copilot-instructions.md`). Either edit the field directly or use:

```bash
poetry version patch   # bug fix:     2.5.5 -> 2.5.6
poetry version minor   # new feature: 2.5.5 -> 2.6.0
poetry version major   # breaking:    2.5.5 -> 3.0.0
```

## Building

```bash
poetry build                 # creates sdist + wheel in dist/
```

## Validate Metadata

```bash
poetry run pip install --quiet twine   # if twine not already available
poetry run twine check dist/*          # validate long_description/metadata
```

## Verify the Built Artifact (a green build is not a correct wheel)

`poetry build` succeeding only means the backend ran — not that the wheel
contains your code. Always inspect wheel contents before publishing:

```bash
python -m zipfile -l dist/*.whl
```

Confirm the whole package ships — `pdm_datareader/__init__.py` **and**
`pdm_datareader/tools.py` — not just a top-level file. `twine check` validates
metadata, not contents, so it won't catch a missing module.

Then prove it from a clean install, outside the repo root (so `import` doesn't
pick up the source tree):

```bash
python -m venv /tmp/verify
/tmp/verify/bin/python -m pip install dist/*.whl
cd /tmp && /tmp/verify/bin/python -c "from pdm_datareader import tools; tools.query"
```

On Windows PowerShell:

```powershell
python -m venv $env:TEMP\verify
& "$env:TEMP\verify\Scripts\python.exe" -m pip install (Get-ChildItem dist\*.whl)
Push-Location $env:TEMP
& "$env:TEMP\verify\Scripts\python.exe" -c "from pdm_datareader import tools; tools.query"
Pop-Location
```

Assert on a real symbol (`tools.query`), never just that the top-level name
imports — a shadowing empty package can make a bare `import` succeed and prove
nothing.

## Publishing to PyPI

Test on TestPyPI first, then publish to production:

```bash
# TestPyPI (one-time config)
poetry config repositories.testpypi https://test.pypi.org/legacy/
poetry publish -r testpypi --build

# Production PyPI (uses a configured token)
poetry publish --build
```

Configure the token once with:

```bash
poetry config pypi-token.pypi <your-token>
```

Never hardcode or commit tokens. Prefer trusted publishing from CI over a
locally stored token where available.

## Dependency Best Practices

```toml
# DO: caret / bounded ranges (poetry style)
msal-bearer = ">=1.3.0,<2.0.0"
pyodbc = "^5.1.0"

# DON'T: exact pins that lock users to one release
pyodbc = "5.1.0"
```

Keep `python = "^3.11"` aligned with the supported versions in the project docs
(3.11–3.13).

## Checklist

```
Before Release:
- [ ] Version bumped under [tool.poetry] (SemVer)
- [ ] README.md updated for any new feature
- [ ] pytest passes and black formatting applied
- [ ] poetry build succeeds
- [ ] poetry run twine check dist/* passes
- [ ] python -m zipfile -l dist/*.whl shows pdm_datareader/__init__.py + tools.py
- [ ] Installed the wheel into a clean venv and imported tools.query from
      a directory outside the repo
- [ ] Tested on TestPyPI first

After Release:
- [ ] pip install pdm-datareader works
- [ ] from pdm_datareader import query works
- [ ] GitHub release / tag created
```
