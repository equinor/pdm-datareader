# Google-Style Python Docstrings

Use this reference when writing or reviewing Python docstrings. The examples
follow the Google style convention.

## Module docstrings

Start each Python module with a docstring that explains its purpose. Include
examples, module attributes, or TODOs when they help users understand the
module.

```python
"""Utilities for authentication and session management.

This module provides token generation and session lifecycle helpers.

Attributes:
    DEFAULT_TOKEN_EXPIRY: Default token expiration time in seconds.
"""
```

## Class docstrings

Describe the class purpose and document its important attributes. Add an
example when it helps explain normal usage. Document constructor arguments in
the `__init__` docstring.

```python
class UserRepository:
    """Manage persistence for user records.

    Attributes:
        connection: Database connection used for operations.
        table_name: Name of the users table.
    """

    def __init__(self, connection: DatabaseConnection) -> None:
        """Initialize the repository.

        Args:
            connection: Active database connection to use.
        """
        self.connection = connection
```

## Functions and methods

Document a function's purpose, parameters, return value, and exceptions where
relevant. Include examples for complex functions.

```python
def calculate_discount(price: float, percentage: float) -> float:
    """Calculate a discounted price.

    Args:
        price: Original item price.
        percentage: Discount percentage from 0 to 100.

    Returns:
        The price after applying the discount.

    Raises:
        ValueError: If percentage is outside the range 0 to 100.
    """
    if not 0 <= percentage <= 100:
        raise ValueError("Percentage must be between 0 and 100")
    return price * (1 - percentage / 100)
```

For complex signatures, explain constraints and defaults in `Args`. Avoid
repeating type information that is already clear from type annotations.

## Async functions

Describe asynchronous behavior and relevant failure conditions in the same
sections used for regular functions.

```python
async def fetch_user_data(user_id: int, timeout: float = 30.0) -> UserData:
    """Fetch user data from the remote service.

    Args:
        user_id: Identifier of the user to fetch.
        timeout: Maximum wait time in seconds.

    Returns:
        Data for the requested user.

    Raises:
        UserNotFoundError: If no user exists with the given ID.
        TimeoutError: If the request exceeds the timeout.
    """
```

## Generators and iterators

Use `Yields` to describe the values yielded by a generator.

```python
def paginate_results(
    query: Query,
    page_size: int = 100,
) -> Iterator[list[Record]]:
    """Paginate through query results.

    Args:
        query: Query whose results are paginated.
        page_size: Maximum number of records per page.

    Yields:
        Pages of records, each with at most `page_size` items.
    """
```

## Properties

Property docstrings should describe the value returned, including relevant
conditions.

```python
@property
def full_name(self) -> str:
    """Return the user's full name, or an empty string if unset."""
    return f"{self.first_name} {self.last_name}".strip()
```

## Context managers

Use `Yields` to describe the value made available inside the context.

```python
@contextmanager
def database_transaction(
    connection: Connection,
) -> Iterator[Transaction]:
    """Manage a database transaction.

    Args:
        connection: Active database connection.

    Yields:
        Transaction object for executing queries.

    Raises:
        TransactionError: If the transaction cannot be started.
    """
```

## Data classes, models, and enums

Document meaningful fields in `Attributes`, especially constraints or
semantics that are not evident from the field name or type.

```python
@dataclass
class OrderItem:
    """Represent one item in an order.

    Attributes:
        product_id: Identifier of the product.
        quantity: Number of units ordered; must be positive.
        unit_price: Price per unit in the order currency.
    """

    product_id: str
    quantity: int
    unit_price: Decimal
```

For enums, describe the lifecycle or meaning of the values. For Pydantic
models, document the model and any field constraints that are not clear from
the declarations.

## Exceptions

Describe when the exception is raised and document custom attributes when
present. Its initializer should document its arguments.

```python
class ValidationError(Exception):
    """Raised when input validation fails.

    Attributes:
        field: Name of the invalid field.
        message: Human-readable error description.
    """

    def __init__(self, field: str, message: str) -> None:
        """Initialize the validation error.

        Args:
            field: Name of the invalid field.
            message: Description of the validation failure.
        """
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")
```

## Supported sections

| Section | Purpose |
| --- | --- |
| `Args` | Document function or method parameters. |
| `Returns` | Describe the returned value. |
| `Yields` | Describe values produced by generators or context managers. |
| `Raises` | List relevant exceptions and when they occur. |
| `Attributes` | Document class or module attributes. |
| `Example` / `Examples` | Show representative usage. |
| `Note` / `Warning` | Call out caveats or important behavior. |
| `Todo` | Record planned improvements. |
| `See Also` | Link related functions, classes, or resources. |

## Best practices

- Keep the first line concise (ideally under 79 characters) and use imperative
  mood, such as “Calculate the total” rather than “Calculates the total.”
- Document every public module, function, class, and method.
- Use examples when they clarify non-obvious usage.
- Document relevant exceptions and non-obvious behavior.
- Keep docstrings synchronized with code changes.
- Indent continuation lines consistently.
