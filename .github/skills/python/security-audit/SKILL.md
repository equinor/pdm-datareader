---
name: auditing-pdm-datareader-security
description: Audits the pdm-datareader library for security vulnerabilities using Bandit, pip-audit, Semgrep, and detect-secrets. Focuses on this project's real risks — SQL injection through query(), Azure AD access-token handling, and tokens or credentials leaking through tracebacks and logs. Use when reviewing library security, setting up security scanning in CI, or implementing secure coding patterns in pdm_datareader.
---

# pdm-datareader Security Auditing

## Quick Start

This project uses **Poetry** (not uv). Run the scanners with `poetry run` /
`pipx run`:

```bash
# High-severity static analysis of the package
pipx run bandit -r pdm_datareader/ -ll

# Audit this project's dependencies (reads the Poetry lock via the env)
poetry run pip-audit

# Pattern-based SAST
pipx run semgrep --config auto pdm_datareader/

# Secrets detection (tokens, connection strings)
pipx run detect-secrets scan > .secrets.baseline
```

## Tool Configuration

**Bandit (.bandit):**

```yaml
exclude_dirs: [tests/, examples/, .venv/]
skips: [B101]  # assert_used - OK in tests
```

**pip-audit:**

```bash
poetry run pip-audit            # Audit the resolved environment
poetry run pip-audit --fix      # Attempt to bump vulnerable pins
```

## Common Vulnerabilities

| Issue | Bandit ID | Fix |
| --- | --- | --- |
| SQL injection | B608 | Use bind parameters via `params=` in `query()` |
| Hardcoded secrets / tokens | B105, B106 | Use `set_token()` / msal-bearer auth, never literals |
| Weak crypto | B303 | `_token_key` uses SHA-256; never downgrade to MD5/SHA1 |
| Pickle untrusted data | B301 | Use JSON instead |
| Path traversal | B108 | Validate with `Path.resolve()` |

## Secure Patterns

This library's primary attack surface is the `query()` function in
[pdm_datareader/tools.py](pdm_datareader/tools.py). Always bind dynamic values.

```python
# SQL - Parameterized query (bind params, never f-strings)
query("SELECT * FROM wells WHERE id = :id", params={"id": user_id})

# UNSAFE - string interpolation exposes SQL injection
query(f"SELECT * FROM wells WHERE id = {user_id}")  # never do this

# Tokens - set explicitly or rely on msal-bearer impersonation
set_token(os.environ["PDM_TOKEN"])   # not a hardcoded literal

# Never log or print the raw access token
# Use _token_key(...) (SHA-256 digest) when an identity fingerprint is needed
```

## Access Tokens Must Not Leak Through Tracebacks or Logs

`connect_to_db` packs an Azure AD access token into `tokenstruct` and passes it
to the driver via `attrs_before`. That token, and the raw string returned by
`get_token()`, are exactly the kind of value that a rich traceback renderer or a
verbose log dumps as a frame local — turning an ordinary exception into a
credential leak in CI logs.

Keep local-variable rendering disabled anywhere logs can leave the machine:

```python
from rich.traceback import install

install(show_locals=False)
```

Also verify the existing `verbose=True` paths in `tools.py` only print
connection *status* messages, never the token or `tokenstruct`. Exercise the
installed exception hook with a sentinel secret to catch regressions:

```python
import sys

def test_unhandled_traceback_does_not_expose_token(capsys):
    sentinel = "sentinel-token-that-must-not-appear"

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        exc_type, exc, traceback = sys.exc_info()
        sys.excepthook(exc_type, exc, traceback)

    output = capsys.readouterr()
    rendered = output.out + output.err
    assert "RuntimeError: boom" in rendered  # proves the hook rendered
    assert sentinel not in rendered
```

Use a unique sentinel, never a real credential. Assert both that the exception
was rendered and that the sentinel was absent; a bypassed output path must not
make the test pass vacuously.

## CI Integration

```yaml
# .github/workflows/security.yml
- uses: actions/setup-python@v5
  with:
    python-version: "3.11"
- run: pipx install poetry
- run: poetry install
- run: pipx run bandit -r pdm_datareader/ -ll
- run: poetry run pip-audit
```

## Audit Checklist

```text
Code:
- [ ] No SQL injection — all dynamic values go through query(..., params=...)
- [ ] No hardcoded tokens or connection secrets (use set_token / env vars)
- [ ] verbose logging and tracebacks never print the token or tokenstruct
- [ ] Exception/logging config cannot render frame locals containing the token
- [ ] Token fingerprints use SHA-256 (_token_key); no MD5/SHA1
- [ ] Input validation on external data
- [ ] Cached engine is scoped to the token identity and TTL (get_engine)

Dependencies:
- [ ] pip-audit clean (pyodbc, pandas, sqlalchemy, msal-bearer, urllib3)
- [ ] Minimal dependencies
- [ ] From trusted sources

CI:
- [ ] Security scan on every PR
- [ ] Weekly dependency scan
```
