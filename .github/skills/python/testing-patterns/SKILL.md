---
name: testing-pdm-datareader-with-pytest
description: Write and run pytest tests for the pdm-datareader library, focused on mocking the parts that cannot run in CI — pyodbc/SQLAlchemy engines and connections, Azure AD access tokens (msal-bearer), and query() execution. Covers module-global state resets, engine-cache assertions, and token-leak safety checks. Use when adding tests for tools.py, mocking database or auth, or fixing failing/ flaky tests.
---

# Testing pdm-datareader with pytest

## Quick Start

```bash
# Run the whole suite
pytest

# Run one file / one test with verbose output
pytest tests/test_engine_cache.py -v
pytest tests/test_engine_cache.py::test_engine_is_cached_for_same_token -v

# Stop on first failure, show locals
pytest -x -l
```

Config lives in `pytest.ini`. Tests live in `tests/` and import the package as
`from pdm_datareader import tools`.

## Core Principle: never touch real DB or AD

`pdm_datareader` talks to SQL Server over ODBC and fetches Azure AD tokens.
Neither is available in CI, so **every test mocks at the boundary**:

- The SQLAlchemy engine / connection (so no ODBC driver or network is needed).
- Token acquisition (`get_token`, `msal_bearer`) — inject a fake token instead.

Prefer testing the pure logic (engine caching, token-key derivation, state
resets) directly, and mock only the true external edges.

## Pattern 1: Reset module-global state between tests

`tools.py` keeps module-level globals (`_engine`, `_engine_token`, `_token`,
`_user_name`). Leaking these across tests causes flakiness. Always use an
autouse fixture to reset:

```python
import pytest
from pdm_datareader import tools


@pytest.fixture(autouse=True)
def reset_state():
    """Ensure a clean engine cache and token before/after each test."""
    tools.reset_engine()
    tools.set_token("")
    yield
    tools.reset_engine()
    tools.set_token("")
```

## Pattern 2: Prefer monkeypatch/setattr over touching globals directly

Use `monkeypatch` so changes are auto-reverted:

```python
def test_engine_rebuilt_after_ttl_expiry(monkeypatch):
    token = b"token-a"
    engine1 = tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=token)

    # Simulate time passing beyond the engine TTL.
    monkeypatch.setattr(
        tools,
        "_engine_created_at",
        tools._engine_created_at - tools._ENGINE_TTL_SECONDS - 1,
    )
    engine2 = tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=token)

    assert engine1 is not engine2
```

## Pattern 3: Mock token acquisition (Azure AD / msal-bearer)

Never call real AD. Patch the token getter or inject via `set_token`:

```python
def test_query_uses_injected_token(monkeypatch):
    tools.set_token("fake-token")
    # or patch the acquisition path:
    monkeypatch.setattr(tools, "get_token", lambda username="": "fake-token")
```

## Pattern 4: Mock the SQLAlchemy engine / connection for query()

Patch `create_engine` (or `tools.get_engine`) so `query()` never opens a real
connection. Use a context-manager mock that mimics `engine.connect()`:

```python
from unittest.mock import MagicMock
import pandas as pd


def test_query_returns_dataframe(monkeypatch):
    fake_conn = MagicMock()

    fake_engine = MagicMock()
    fake_engine.connect.return_value.__enter__.return_value = fake_conn

    monkeypatch.setattr(tools, "get_engine", lambda *a, **k: fake_engine)
    monkeypatch.setattr(
        pd, "read_sql", lambda sql, con, params=None: pd.DataFrame({"x": [1]})
    )

    df = tools.query("SELECT 1")  # adjust to the real public signature
    assert list(df["x"]) == [1]
```

Tip: mock at the smallest useful seam. If `query()` calls `pd.read_sql`, mock
that; if it uses `conn.execute`, set `fake_conn.execute.return_value` instead.

## Pattern 5: Assert on identity for cache behavior

Engine caching is verified with `is` / `is not`, not equality:

```python
assert engine1 is engine2       # same token reuses cached engine
assert engine_a is not engine_b # different identity rebuilds
```

## Pattern 6: Security regression tests (tokens must not leak)

Keep tests that prove secrets never surface — in cached state or tracebacks:

```python
def test_engine_token_is_not_stored_raw():
    token = b"super-secret-token"
    tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=token)
    assert tools._engine_token != token
    assert tools._engine_token == tools._token_key(token)
```

Use `capsys` to assert a sentinel token never appears in rendered output
(see `tests/test_traceback_no_token_leak.py`).

## Conventions

- Name test files `test_*.py`, functions `test_*`.
- One behavior per test; put the assertion intent in a short docstring/comment.
- Use `pytest.raises` for expected errors:
  ```python
  with pytest.raises(ValueError):
      tools.get_token(username=123)  # invalid type
  ```
- Prefer `monkeypatch` and fixtures over manual setup/teardown.
- Do not assert on raw token bytes anywhere except the "not stored raw" check.

## Checklist before committing tests

- [ ] No real network, ODBC driver, or AD call is required to run `pytest`.
- [ ] Module globals reset via an autouse fixture.
- [ ] New public function in `tools.py` has at least one test.
- [ ] No secret/token value is printed or asserted in plaintext output.
- [ ] `pytest` passes locally and `black .` leaves the tests unchanged.
