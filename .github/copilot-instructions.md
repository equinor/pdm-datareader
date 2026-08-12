# PDM DataReader Copilot Instructions

## Project Overview
`pdm-datareader` is a Python package for querying Production Data Mart (PDM) tables using SQL. It provides authentication handling for Equinor environments with user impersonation capabilities.

## Tech Stack
- **Language**: Python 3.11 - 3.13
- **Build Tool**: Poetry
- **Testing**: pytest
- **Dependencies**: pyodbc, pandas, sqlalchemy, msal-bearer, urllib3

## Key Files & Directories
- `pdm_datareader/`: Main package code
- `pdm_datareader/__init__.py`: Entry point with `query()` function
- `pdm_datareader/tools.py`: Core authentication and query execution logic
- `tests/`: Unit tests (using pytest)
- `examples/demo.py`: Usage examples
- `pyproject.toml`: Poetry project configuration

## Development Workflow

### Running Tests
```bash
pytest
```

### Linting & Formatting
`black` is the configured formatter (dev dependency). Format before committing:
```bash
black .
```

### Building & Publishing
Poetry handles packaging and distribution via PyPI. Use the
`packaging-python-libraries` skill
(`.github/skills/python/packaging-python-libraries/SKILL.md`) for building the
sdist/wheel, validating with twine, verifying wheel contents, and publishing to
PyPI.

## Code Standards & Guidelines

1. **Python Style**: Follow PEP 8 conventions (see the PEP 8 Style Guide section below)
2. **Formatting**: Run `black .` to auto-format; do not hand-format against black's output
3. **Type Hints**: Use type hints on all public functions; import from `typing` (e.g. `Optional`)
4. **Docstrings**: Include Google-style docstrings for all public functions (Args/Returns)
5. **Testing**: All features must have corresponding unit tests
6. **Authentication**: Use `msal-bearer` for Equinor AD authentication; never hardcode credentials

## PEP 8 Style Guide

Follow PEP 8 as enforced by `black`. Key conventions used in this codebase:

- **Indentation**: 4 spaces per level; never use tabs.
- **Line length**: Keep lines to black's default (88 chars); wrap long call arguments one per line.
- **Naming**:
  - `snake_case` for functions, variables, and module-level names (`get_token`, `connect_to_db`).
  - Module-private globals are prefixed with a single underscore (`_engine`, `_token`, `_user_name`).
  - `UPPER_CASE` for constants (`SQL_COPT_SS_ACCESS_TOKEN`).
- **Imports**: Group in order — standard library, third-party, then local — separated by blank lines. One import per line.
- **Type hints**: Annotate parameters and return types (`def query(sql: str, params: Optional[dict] = None) -> pd.DataFrame`).
- **Docstrings**: Google-style with `Args:` and `Returns:` sections, matching existing functions in `tools.py`.
- **Whitespace**: No trailing whitespace; two blank lines between top-level functions; no spaces inside parentheses.
- **Global state**: When mutating module-level globals (`_engine`, `_token`), declare `global` at the top of the function, as done in `tools.py`.
- **Comparisons/booleans**: Use `if not x:` for emptiness checks rather than `if x == ""` or `len(x) == 0`.

## Common Tasks

### When fixing bugs:
- Look in `pdm_datareader/tools.py` for the query execution logic
- Check `tests/` for existing test cases covering the bug area
- Ensure backward compatibility with existing user code

### When adding features:
- Add the feature to appropriate module in `pdm_datareader/`
- Write unit tests in `tests/` (use the `testing-patterns` skill,
  `.github/skills/python/testing-patterns/SKILL.md`)
- Update `examples/demo.py` if it's a user-facing feature
- Update docstrings in the main module

### When updating dependencies:
- Update `pyproject.toml` with new version constraints
- Test thoroughly with `pytest` to ensure no breaking changes
- Document any breaking changes in PR description

### When packaging or publishing a release:
- Use the `packaging-python-libraries` skill
  (`.github/skills/python/packaging-python-libraries/SKILL.md`) for Poetry-based
  builds, twine metadata/wheel-content checks, clean-install verification, and
  publishing to TestPyPI/PyPI

### When writing tests:
- Use the `testing-patterns` skill
  (`.github/skills/python/testing-patterns/SKILL.md`) for mocking pyodbc/
  SQLAlchemy engines and Azure AD tokens, resetting module globals, and
  token-leak regression tests

### When reviewing security:
- Use the `security-audit` skill (`.github/skills/python/security-audit/SKILL.md`)
  for auditing SQL injection, token/credential leaks, and dependency scanning

## Versioning

Bump the `version` field under `[tool.poetry]` in `pyproject.toml` for every
change, following [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.MICRO`):

- **MAJOR**: Increment for breaking changes that are **not** backward compatible
  (e.g. removing or renaming public functions, changing function signatures or
  return types). Reset MINOR and MICRO to `0`.
- **MINOR**: Increment when new functionality or features are added, such as new
  functions within existing modules/classes. Always backward compatible within
  the same MAJOR version. Reset MICRO to `0`.
- **MICRO** (patch): Increment for bug fixes and minor, non-breaking changes that
  improve existing functionality. No new features — only improvements and fixes.

Example: `2.5.4` → `2.5.5` (bug fix), → `2.6.0` (new feature), → `3.0.0`
(breaking change).


## Important Notes
- This package must run from Equinor managed environments
- Authentication requires ODBC Driver for SQL Server (v17 or v18)
- Parameter bindings are preferred for SQL queries to prevent injection
- The package is open source (MIT License) but targeted at Equinor users

## Resources
- README.md: Installation and basic usage
- examples/demo.py: Practical usage examples
- tests/: Test cases demonstrating features

## Documentation
- Update README.md for any new features
- Include inline comments for complex logic