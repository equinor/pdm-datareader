# PDM DataReader Copilot Instructions

## Project Overview
`pdm-datareader` is a Python package for querying Production Data Mart (PDM) tables using SQL. It provides authentication handling for Equinor environments with user impersonation capabilities.

## Tech Stack
- **Language**: Python 3.9.2 - 3.12
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
```bash
black .
ruff check . --select E,W
```

### Building & Publishing
Poetry handles packaging and distribution via PyPI.

## Code Standards & Guidelines

1. **Python Style**: Follow PEP 8 conventions
2. **Type Hints**: Use type hints where possible for better IDE support
3. **Docstrings**: Include docstrings for all public functions
4. **Testing**: All features must have corresponding unit tests
5. **Authentication**: Use `msal-bearer` for Equinor AD authentication; never hardcode credentials

## Common Tasks

### When fixing bugs:
- Look in `pdm_datareader/tools.py` for the query execution logic
- Check `tests/` for existing test cases covering the bug area
- Ensure backward compatibility with existing user code

### When adding features:
- Add the feature to appropriate module in `pdm_datareader/`
- Write unit tests in `tests/`
- Update `examples/demo.py` if it's a user-facing feature
- Update docstrings in the main module

### When updating dependencies:
- Update `pyproject.toml` with new version constraints
- Test thoroughly with `pytest` to ensure no breaking changes
- Document any breaking changes in PR description

## Important Notes
- This package must run from Equinor managed environments
- Authentication requires ODBC Driver for SQL Server (v17 or v18)
- Parameter bindings are preferred for SQL queries to prevent injection
- The package is open source (MIT License) but targeted at Equinor users

## Resources
- README.md: Installation and basic usage
- examples/demo.py: Practical usage examples
- tests/: Test cases demonstrating features
