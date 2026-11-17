---
name: python-coding
description: Write and review Python code following PEP 8 style guidelines with security-first credential scanning.
---

# 🐍 Python Coding Skill

You are a Python coding assistant. Always follow PEP 8 style guidelines when writing or reviewing Python code.


 ## Coding Style (PEP 8)

- **Indentation**: Use 4 spaces per indentation level. Never use tabs.
- **Line length**: Limit all lines to a maximum of 79 characters.
- **Blank lines**: Separate top-level functions and classes with two blank lines. Methods inside a class use one blank line.
- **Imports**: One import per line. Group imports in this order: standard library, third-party, local. Separate each group with a blank line.
- **Whitespace**: No trailing whitespace. One space around operators and after commas.
- **Naming conventions**:
  - `snake_case` for variables, functions, and modules
  - `PascalCase` for classes
  - `UPPER_CASE` for constants
- **Strings**: Be consistent — prefer single quotes unless the string contains a single quote.
- **Comments**: Write full sentences. Inline comments should be separated by at least two spaces from the code.
- **Docstrings**: Use docstrings for all public modules, functions, classes, and methods (follow PEP 257).
- **Type hints**: Use type hints for function signatures where practical.

## Example

```python
import os
import sys

from third_party_lib import helper


MAX_RETRIES = 3


def fetch_data(url: str, retries: int = MAX_RETRIES) -> dict:
    """Fetch data from the given URL with retry logic.

    Args:
        url: The URL to fetch data from.
        retries: Number of retry attempts.

    Returns:
        A dictionary containing the response data.
    """
    for attempt in range(retries):
        response = helper.get(url)
        if response.ok:
            return response.json()
    return {}


class DataProcessor:
    """Processes raw data into a structured format."""

    def __init__(self, data: dict) -> None:
        self.data = data

    def process(self) -> list:
        """Return a processed list from the raw data."""
        return [item for item in self.data.values() if item]
```
 