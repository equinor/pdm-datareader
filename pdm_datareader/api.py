"""Client for the PDM REST API, accessed through Azure API Management (APIM).

The main entry point is :func:`read_api_view`, which reads one PDM view through the
API's flex endpoint and returns it as a :class:`pandas.DataFrame`.

Authentication uses an Azure AD access token for the signed-in user (public
client flow via ``msal-bearer``) plus an APIM subscription key. By default the
subscription key is read from Azure Key Vault with the signed-in user's own
access; it can be overridden with :func:`set_subscription_key` or the
``PDM_APIM_SUBSCRIPTION_KEY`` environment variable.
"""

import base64
import datetime as dt
import json
import math
import numbers
import os
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from email.utils import parsedate_to_datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
import requests
from msal_bearer import BearerAuth

TENANT_ID = "3aa4a235-b6e2-48d5-9195-7fcf05b459b0"
PROD_CLIENT_ID = "9ed0d36d-1034-475a-bdce-fa7b774473fb"

ENV_VAR_ENVIRONMENT = "PDM_API_ENV"
ENV_VAR_BASE_URL = "PDM_API_BASE_URL"
ENV_VAR_CLIENT_ID = "PDM_API_CLIENT_ID"
ENV_VAR_SUBSCRIPTION_KEY = "PDM_APIM_SUBSCRIPTION_KEY"
ENV_VAR_KEY_VAULT_URL = "PDM_KEY_VAULT_URL"

SUBSCRIPTION_KEY_HEADER = "Ocp-Apim-Subscription-Key"

# TODO: set to the real vault once it exists. Until then, set
# PDM_KEY_VAULT_URL or supply the subscription key directly.
KEY_VAULT_URL = "https://<vault-name>.vault.azure.net"
KEY_VAULT_SCOPE = "https://vault.azure.net/.default"
KEY_VAULT_API_VERSION = "7.4"
_KEY_VAULT_TIMEOUT_SECONDS = 30.0
_KEY_VAULT_URL_PATTERN = re.compile(
    r"^https://[a-z0-9](?:[a-z0-9-]{1,22}[a-z0-9])?\.vault\.azure\.net/?$",
    re.IGNORECASE,
)
_SECRET_NAME_PATTERN = re.compile(r"^[0-9A-Za-z-]{1,127}$")

DEFAULT_TIMEOUT_SECONDS = 300.0
_CONNECT_TIMEOUT_SECONDS = 10.0
_MAX_RETRIES = 3
_MAX_RETRY_DELAY_SECONDS = 60.0
_RETRY_STATUS_CODES = frozenset({429, 502, 503})

# Characters with a meaning in the flex filter syntax. The API has no escape
# mechanism (quoted values are still parsed as functions), so values containing
# them are rejected instead of being sent with a different meaning.
_RESERVED_FILTER_CHARS = frozenset('|,[]()"')

_RESERVED_PARAM_NAMES = frozenset({"top", "skip", "columns", "orderby"})

_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ORDER_BY_PATTERN = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)(?:\s+(ASC|DESC))?\s*$", re.IGNORECASE
)
_ISO_DATETIME_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$"
)


@dataclass(frozen=True)
class ApiEnvironment:
    """Connection settings for one PDM API environment.

    Attributes:
        name (str): Environment name, e.g. ``"prod"`` or ``"test"``.
        base_url (str): APIM base URL, without the trailing ``/api``.
        scope (str): Azure AD scope to request access tokens for.
        client_id (str): Azure AD public client (app registration) ID.
        key_vault_secret (str): Name of the Key Vault secret holding the APIM
            subscription key for this environment's gateway.
    """

    name: str
    base_url: str
    scope: str
    client_id: str
    key_vault_secret: str


ENVIRONMENTS: Dict[str, ApiEnvironment] = {
    "prod": ApiEnvironment(
        name="prod",
        base_url="https://api.gateway.equinor.com/pdm-internal-api/v3",
        scope="https://proxy-pdm-api-prod-external.radix.equinor.com/.default",
        client_id=PROD_CLIENT_ID,
        key_vault_secret="pdm-apim-subscription-key",
    ),
    "test": ApiEnvironment(
        name="test",
        base_url="https://api-test.gateway.equinor.com/pdm-internal-api/v3",
        scope="https://proxy-pdm-api-test-external.radix.equinor.com/.default",
        client_id=PROD_CLIENT_ID,
        key_vault_secret="pdm-apim-subscription-key-test",
    ),
}

_environment_name = ""
_api_token = ""
_api_user_name = ""
_subscription_key = ""
# Subscription keys read from Key Vault, keyed by (vault URL, secret name).
# Kept in memory only, never written to disk.
_vault_keys: Dict[Tuple[str, str], str] = {}
_session: Optional[requests.Session] = None


class PdmApiError(Exception):
    """Error returned by, or while talking to, the PDM API.

    Attributes:
        status_code (Optional[int]): HTTP status code, if a response was received.
        trace_id (Optional[str]): Server trace ID, if the API returned one.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        trace_id: Optional[str] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.trace_id = trace_id


class SubscriptionKeyError(PdmApiError):
    """The APIM subscription key is missing or was rejected by the gateway."""


class PdmAuthError(PdmApiError):
    """The access token was rejected (401) or access was denied (403)."""


class PdmTimeoutError(PdmApiError):
    """The request timed out on the client, the gateway or the backend."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def set_environment(name: str) -> None:
    """Select the API environment to use.

    Takes precedence over the ``PDM_API_ENV`` environment variable. Pass an
    empty string to fall back to ``PDM_API_ENV`` or the default (``"prod"``).
    A token set with :func:`set_api_token` is not cleared when switching, so
    set a token for the new environment as well if you use one.

    Args:
        name (str): One of the keys in :data:`ENVIRONMENTS` (``"prod"``,
            ``"test"``), or an empty string.

    Raises:
        ValueError: If ``name`` is not a known environment.
    """
    global _environment_name

    if name and name.lower() not in ENVIRONMENTS:
        raise ValueError(
            f"Unknown environment {name!r}. Valid values: {sorted(ENVIRONMENTS)}."
        )
    _environment_name = name.lower()


def get_environment() -> ApiEnvironment:
    """Get the active API environment, including any overrides.

    Resolution order: :func:`set_environment`, then the ``PDM_API_ENV``
    environment variable, then ``"prod"``. The base URL and client ID can be
    overridden with ``PDM_API_BASE_URL`` and ``PDM_API_CLIENT_ID``.

    Returns:
        ApiEnvironment: Settings for the active environment.

    Raises:
        ValueError: If ``PDM_API_ENV`` names an unknown environment.
    """
    name = (_environment_name or os.getenv(ENV_VAR_ENVIRONMENT, "") or "prod").lower()
    if name not in ENVIRONMENTS:
        raise ValueError(
            f"Unknown environment {name!r} in {ENV_VAR_ENVIRONMENT}. "
            f"Valid values: {sorted(ENVIRONMENTS)}."
        )
    env = ENVIRONMENTS[name]

    base_url = os.getenv(ENV_VAR_BASE_URL, "").strip() or env.base_url
    client_id = os.getenv(ENV_VAR_CLIENT_ID, "").strip() or env.client_id
    return ApiEnvironment(
        name=env.name,
        base_url=base_url.rstrip("/"),
        scope=env.scope,
        client_id=client_id,
        key_vault_secret=env.key_vault_secret,
    )


def set_api_token(token: str) -> None:
    """Set an API access token explicitly instead of using user-impersonation.

    This is separate from :func:`pdm_datareader.tools.set_token`, which holds
    the token for the direct database connection. Pass an empty string to go
    back to user-impersonation.

    Args:
        token (str): Access token for the PDM API.
    """
    global _api_token
    _api_token = token


def _normalize_username(username: str) -> str:
    """Normalize a user name for the token cache lookup.

    A short name gets ``@equinor.com`` appended; full addresses are kept.
    Case does not matter for the lookup.

    Args:
        username (str): Short name or email address.

    Returns:
        str: The user name as an email address.
    """
    username = username.strip()
    if "@" not in username:
        username = f"{username}@equinor.com"
    return username


def _username_from_token(token: str) -> str:
    """Read the signed-in user's name from an access token.

    The token is decoded without verification, only to learn which account
    was used so later lookups in the token cache find it again.

    Args:
        token (str): JWT access token.

    Returns:
        str: The ``upn``, ``preferred_username`` or ``unique_name`` claim, or
        an empty string if none can be read.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, TypeError):
        return ""
    if not isinstance(claims, dict):
        return ""
    for claim in ("upn", "preferred_username", "unique_name"):
        value = claims.get(claim)
        if isinstance(value, str) and value:
            return value
    return ""


def get_api_token(username: str = "") -> str:
    """Get an access token for the PDM API.

    Returns the token set with :func:`set_api_token` if any. Otherwise gets a
    token for the active environment through ``msal-bearer``, silently from
    its cache when possible and interactively (browser login) when needed.

    The account is chosen in this order: ``username`` if given, then the
    account used for the previous API token in this session, then the
    account already in the token cache (if there are several, the first is
    used; pass ``username`` to choose). The Windows login name is not used,
    as it often differs from the Equinor account name.

    Args:
        username (str, optional): Short name or email address of the account
            to use, e.g. ``"abcd"`` or ``"abcd@equinor.com"``.

    Returns:
        str: Access token string.
    """
    if _api_token:
        return _api_token

    return _acquire_token(get_environment().scope, username)


def _acquire_token(scope: str, username: str = "") -> str:
    """Get a user token for ``scope`` through ``msal-bearer``.

    Shared by the API and Key Vault tokens so both use the same account
    selection (see :func:`get_api_token`).

    Args:
        scope (str): Scope to request, e.g. the API or Key Vault scope.
        username (str, optional): Account to use, overriding the remembered one.

    Returns:
        str: Access token string.
    """
    global _api_user_name

    if username:
        _api_user_name = _normalize_username(username)

    auth = BearerAuth.get_auth(
        tenantID=TENANT_ID,
        clientID=get_environment().client_id,
        scopes=[scope],
        username=_api_user_name,
    )
    # Remember the account actually signed in with, so the next call finds it
    # in the token cache instead of opening a new browser login.
    _api_user_name = _username_from_token(auth.token) or _api_user_name
    return auth.token


def set_subscription_key(key: str) -> None:
    """Set the APIM subscription key explicitly.

    Overrides both the ``PDM_APIM_SUBSCRIPTION_KEY`` environment variable and
    the key from Key Vault, e.g. for users or services with their own
    subscription. Pass an empty string to go back to the default lookup.
    Never commit the key to source control.

    Args:
        key (str): APIM subscription key.
    """
    global _subscription_key
    _subscription_key = key


def _get_subscription_key() -> Tuple[str, bool]:
    """Resolve the APIM subscription key.

    Lookup order: :func:`set_subscription_key`, then the
    ``PDM_APIM_SUBSCRIPTION_KEY`` environment variable, then Key Vault.

    Returns:
        Tuple[str, bool]: The key, and whether it came from Key Vault.

    Raises:
        SubscriptionKeyError: If the key can't be read from Key Vault.
    """
    key = _subscription_key or os.getenv(ENV_VAR_SUBSCRIPTION_KEY, "").strip()
    if key:
        return key, False
    return _get_key_from_vault(), True


def _key_vault_url() -> str:
    """Get and validate the Key Vault URL.

    Only ``https://<name>.vault.azure.net`` URLs are accepted, so a Key Vault
    token is never sent to another host.

    Returns:
        str: The vault URL without a trailing slash.

    Raises:
        SubscriptionKeyError: If the URL is not configured or not valid.
    """
    url = os.getenv(ENV_VAR_KEY_VAULT_URL, "").strip() or KEY_VAULT_URL
    if not _KEY_VAULT_URL_PATTERN.match(url):
        raise SubscriptionKeyError(
            f"No valid Key Vault configured for the subscription key ({url!r}). "
            f"Set {ENV_VAR_KEY_VAULT_URL} to https://<vault-name>.vault.azure.net, "
            f"or supply the key with {ENV_VAR_SUBSCRIPTION_KEY} or "
            "set_subscription_key(...)."
        )
    return url.rstrip("/")


def _get_key_from_vault(refresh: bool = False) -> str:
    """Read the active environment's subscription key from Key Vault.

    Uses a Key Vault token for the signed-in user, so access follows the
    user's own Key Vault permissions. The key is cached in memory for the
    session.

    Args:
        refresh (bool): Ignore the cached value and read the secret again,
            e.g. after the key was rotated.

    Returns:
        str: The subscription key.

    Raises:
        SubscriptionKeyError: If the secret can't be read.
    """
    env = get_environment()
    vault_url = _key_vault_url()
    secret = env.key_vault_secret
    if not _SECRET_NAME_PATTERN.match(secret):
        raise SubscriptionKeyError(f"Invalid Key Vault secret name {secret!r}.")

    cache_key = (vault_url, secret)
    if not refresh and cache_key in _vault_keys:
        return _vault_keys[cache_key]

    override_hint = (
        f"To use a key directly instead, set {ENV_VAR_SUBSCRIPTION_KEY} or call "
        "set_subscription_key(...)."
    )
    try:
        response = _get_session().get(
            f"{vault_url}/secrets/{secret}",
            params={"api-version": KEY_VAULT_API_VERSION},
            headers={"Authorization": "Bearer " + _acquire_token(KEY_VAULT_SCOPE)},
            timeout=(_CONNECT_TIMEOUT_SECONDS, _KEY_VAULT_TIMEOUT_SECONDS),
        )
    except requests.RequestException as err:
        raise SubscriptionKeyError(
            f"Could not reach Key Vault {vault_url}: {type(err).__name__}. "
            + override_hint
        ) from None

    if response.status_code in (401, 403):
        raise SubscriptionKeyError(
            f"No access to secret {secret!r} in Key Vault {vault_url} "
            f"({response.status_code}). Access to the PDM API subscription key "
            "must be granted to your account. " + override_hint,
            response.status_code,
        )
    if response.status_code == 404:
        raise SubscriptionKeyError(
            f"Secret {secret!r} was not found in Key Vault {vault_url}. "
            + override_hint,
            response.status_code,
        )
    if not response.ok:
        message, _ = _error_details(response)
        raise SubscriptionKeyError(
            f"Reading the subscription key from Key Vault failed: "
            f"{response.status_code} {message}. " + override_hint,
            response.status_code,
        )

    try:
        key = response.json()["value"]
    except (ValueError, KeyError, TypeError):
        key = None
    if not isinstance(key, str) or not key.strip():
        raise SubscriptionKeyError(
            f"Secret {secret!r} in Key Vault {vault_url} has no usable value."
        )

    _vault_keys[cache_key] = key.strip()
    return _vault_keys[cache_key]


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------


class _Filter:
    """Base class for flex filter expressions."""

    def to_param(self) -> str:
        """Render the filter as a flex query parameter value.

        Returns:
            str: The filter expression.
        """
        raise NotImplementedError

    def __str__(self) -> str:
        return self.to_param()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.to_param()!r})"

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self.to_param() == other.to_param()

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.to_param()))


class Range(_Filter):
    """Values between ``start`` and ``end``, both inclusive.

    Either end may be omitted for an open range. Works for numbers and
    dates/date-times.

    Example:
        ``Range("2022-01-01", "2022-01-31")`` renders as
        ``RANGE(2022-01-01 | 2022-01-31)``.
    """

    def __init__(self, start: Any = None, end: Any = None):
        if start is None and end is None:
            raise ValueError("Range needs a start, an end, or both.")
        self.start = start
        self.end = end

    def to_param(self) -> str:
        if self.start is None:
            return f"RANGE(| {_format_value(self.end)})"
        if self.end is None:
            return f"RANGE({_format_value(self.start)} |)"
        return f"RANGE({_format_value(self.start)} | {_format_value(self.end)})"


class Like(_Filter):
    """String values containing ``text``."""

    def __init__(self, text: str):
        self.text = text

    def to_param(self) -> str:
        return f"LIKE({_format_text(self.text)})"


class StartsLike(_Filter):
    """String values starting with ``text``."""

    def __init__(self, text: str):
        self.text = text

    def to_param(self) -> str:
        return f"STARTS_LIKE({_format_text(self.text)})"


class EndsLike(_Filter):
    """String values ending with ``text``."""

    def __init__(self, text: str):
        self.text = text

    def to_param(self) -> str:
        return f"ENDS_LIKE({_format_text(self.text)})"


class IsNull(_Filter):
    """Rows where the column is null."""

    def to_param(self) -> str:
        return "ISNULL()"


class In(_Filter):
    """Any of the given values.

    Items can be plain values or other filters (except :class:`In`), e.g.
    ``In([Range(2, 5), 7])``.
    """

    def __init__(self, values: Iterable[Any]):
        if isinstance(values, (str, bytes)):
            raise TypeError("In expects a list of values, not a single string.")
        self.values = list(values)
        if not self.values:
            raise ValueError("In needs at least one value.")
        for value in self.values:
            if isinstance(value, In):
                raise TypeError("In cannot be nested.")

    def to_param(self) -> str:
        items = [
            v.to_param() if isinstance(v, _Filter) else _format_value(v)
            for v in self.values
        ]
        return "[" + ", ".join(items) + "]"


class Raw(_Filter):
    """A filter expression sent exactly as given, without validation.

    For advanced use when the helpers don't cover a case. The caller is
    responsible for the expression being valid flex syntax.
    """

    def __init__(self, expression: str):
        if not isinstance(expression, str) or not expression:
            raise ValueError("Raw needs a non-empty string expression.")
        self.expression = expression

    def to_param(self) -> str:
        return self.expression


def _format_text(text: Any) -> str:
    """Validate a string value used inside a filter.

    Args:
        text: The value; must be a non-empty string.

    Returns:
        str: The validated string.

    Raises:
        TypeError: If ``text`` is not a string.
        ValueError: If ``text`` is empty or contains reserved characters.
    """
    if not isinstance(text, str):
        raise TypeError(f"Expected a string, got {type(text).__name__}.")
    if not text:
        raise ValueError("Filter values cannot be empty strings.")
    bad = sorted(set(text) & _RESERVED_FILTER_CHARS)
    if bad:
        raise ValueError(
            f"Filter value {text!r} contains reserved character(s) {bad}. "
            "The API has no way to escape them; use Like/StartsLike/EndsLike "
            "on a part of the value without them, or Raw(...) if you know "
            "the exact expression to send."
        )
    return text


def _format_value(value: Any) -> str:
    """Render a single value for use in a flex filter.

    Args:
        value: A string, number, bool, date or date-time.

    Returns:
        str: The rendered value.

    Raises:
        TypeError: If the value type is not supported.
        ValueError: If the value cannot be represented safely.
    """
    if isinstance(value, (bool, np.bool_)):
        return "true" if value else "false"
    if isinstance(value, np.datetime64):
        value = pd.Timestamp(value)
    if isinstance(value, (pd.Timestamp, dt.datetime)):
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            raise ValueError(
                "Timezone-aware date-times are not supported; pass a naive "
                "date-time in the database's time zone."
            )
        timespec = "seconds" if ts.microsecond == 0 and ts.nanosecond == 0 else "auto"
        return ts.isoformat(timespec=timespec)
    if isinstance(value, dt.date):
        return f"{value.isoformat()}T00:00:00"
    if isinstance(value, numbers.Integral):
        return str(int(value))
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"Cannot filter on non-finite number {value!r}.")
        return str(value)
    if isinstance(value, numbers.Real):
        if not math.isfinite(value):
            raise ValueError(f"Cannot filter on non-finite number {value!r}.")
        return repr(float(value))
    if isinstance(value, str):
        return _format_text(value)
    raise TypeError(
        f"Unsupported filter value type {type(value).__name__}. Use a string, "
        "number, bool, date/datetime, or one of the filter helpers."
    )


def _filter_param(value: Any) -> str:
    """Render the value of one entry in the ``filters`` dict.

    Args:
        value: A filter helper, a list of values, or a single value.

    Returns:
        str: The rendered filter expression.

    Raises:
        TypeError: If ``value`` is None or of an unsupported type.
    """
    if isinstance(value, _Filter):
        return value.to_param()
    if isinstance(value, (list, tuple, set, frozenset)):
        return In(value).to_param()
    if value is None:
        raise TypeError("Use IsNull() to filter on null values.")
    return _format_value(value)


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------


def _validate_name(name: Any, kind: str) -> str:
    """Validate a resource or column name.

    Args:
        name: The name to validate.
        kind (str): What the name refers to, used in error messages.

    Returns:
        str: The validated name.

    Raises:
        ValueError: If the name is not a plain identifier.
    """
    if not isinstance(name, str) or not _NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid {kind} {name!r}: use letters, digits and underscores only."
        )
    return name


def _split_list(value: Union[str, Sequence[str]]) -> List[str]:
    """Accept a comma-separated string or a sequence of strings.

    Args:
        value: ``"A, B"`` or ``["A", "B"]``.

    Returns:
        List[str]: The individual, stripped items.
    """
    if isinstance(value, str):
        return [item.strip() for item in value.split(",")]
    return [item.strip() if isinstance(item, str) else item for item in value]


def _columns_param(columns: Union[str, Sequence[str]]) -> str:
    """Render the ``Columns`` parameter.

    Args:
        columns: Column names as a list or a comma-separated string.

    Returns:
        str: Comma-separated column names.

    Raises:
        ValueError: If the list is empty or contains invalid names.
    """
    items = _split_list(columns)
    if not items:
        raise ValueError("columns cannot be empty.")
    return ",".join(_validate_name(c, "column name") for c in items)


def _order_by_param(order_by: Union[str, Sequence[str]]) -> str:
    """Render the ``OrderBy`` parameter.

    Args:
        order_by: ``"COL1, COL2 DESC"`` or ``["COL1", "COL2 DESC"]``.

    Returns:
        str: Normalized ``OrderBy`` value, e.g. ``"COL1,COL2 DESC"``.

    Raises:
        ValueError: If the value is empty or an item is not ``COLUMN [ASC|DESC]``.
    """
    items = _split_list(order_by)
    if not items:
        raise ValueError("order_by cannot be empty.")
    rendered = []
    for item in items:
        match = _ORDER_BY_PATTERN.match(item) if isinstance(item, str) else None
        if not match:
            raise ValueError(
                f"Invalid order_by item {item!r}: use 'COLUMN', 'COLUMN ASC' "
                "or 'COLUMN DESC'."
            )
        column, direction = match.group(1), match.group(2)
        rendered.append(f"{column} {direction.upper()}" if direction else column)
    return ",".join(rendered)


def _build_params(
    filters: Optional[Dict[str, Any]],
    columns: Optional[Union[str, Sequence[str]]],
    order_by: Optional[Union[str, Sequence[str]]],
    top: Optional[int],
    skip: Optional[int],
) -> List[Tuple[str, str]]:
    """Build the query parameters for a flex request.

    Args:
        filters: Column name to filter value/helper.
        columns: Columns to return.
        order_by: Sort order.
        top: Maximum number of rows, or None for all rows.
        skip: Number of rows to skip.

    Returns:
        List[Tuple[str, str]]: Query parameters in a stable order.

    Raises:
        ValueError: If any argument is invalid.
        TypeError: If a filter value has an unsupported type.
    """
    # The API returns only 1000 rows when Top is omitted, so always send it.
    if top is None:
        params = [("Top", "ALL")]
    elif isinstance(top, bool) or not isinstance(top, int) or top < 1:
        raise ValueError("top must be a positive integer or None (all rows).")
    else:
        params = [("Top", str(top))]

    if skip is not None:
        if isinstance(skip, bool) or not isinstance(skip, int) or skip < 0:
            raise ValueError("skip must be a non-negative integer or None.")
        params.append(("Skip", str(skip)))

    if columns is not None:
        params.append(("Columns", _columns_param(columns)))

    if order_by is not None:
        params.append(("OrderBy", _order_by_param(order_by)))

    for column, value in (filters or {}).items():
        _validate_name(column, "filter column")
        if column.lower() in _RESERVED_PARAM_NAMES:
            raise ValueError(
                f"{column!r} is a reserved parameter name; use the "
                "top/skip/columns/order_by arguments instead."
            )
        params.append((column, _filter_param(value)))

    return params


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _user_agent() -> str:
    """Build the User-Agent header value.

    Returns:
        str: ``pdm-datareader/<version>``.
    """
    try:
        package_version = version("pdm-datareader")
    except PackageNotFoundError:
        package_version = "unknown"
    return f"pdm-datareader/{package_version}"


def _get_session() -> requests.Session:
    """Get the cached HTTP session, creating it if needed.

    The session holds no credentials; the token and subscription key are
    added per request.

    Returns:
        requests.Session: The shared session.
    """
    global _session

    if _session is None:
        _session = requests.Session()
        _session.headers.update(
            {"User-Agent": _user_agent(), "Accept": "application/json"}
        )
    return _session


def _reset_session() -> None:
    """Close and drop the cached HTTP session."""
    global _session

    if _session is not None:
        _session.close()
        _session = None


def _retry_delay(response: Optional[requests.Response], attempt: int) -> float:
    """Compute how long to wait before retrying.

    Honours ``Retry-After`` (seconds or HTTP date) when present, otherwise
    uses exponential backoff. Capped at ``_MAX_RETRY_DELAY_SECONDS``.

    Args:
        response: The response that triggered the retry, if any.
        attempt (int): Zero-based retry attempt number.

    Returns:
        float: Delay in seconds.
    """
    delay = float(2**attempt)
    header = response.headers.get("Retry-After") if response is not None else None
    if header:
        try:
            delay = float(header)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(header)
                delay = (retry_at - dt.datetime.now(retry_at.tzinfo)).total_seconds()
            except (TypeError, ValueError):
                pass
    return min(max(delay, 0.0), _MAX_RETRY_DELAY_SECONDS)


def _error_details(response: requests.Response) -> Tuple[str, Optional[str]]:
    """Extract a message and trace ID from an error response.

    Handles both APIM errors (``{"statusCode", "message"}``) and backend
    errors (``{"Error", "StatusCode", "ErrorCode", "TraceId"}``).

    Args:
        response: The error response.

    Returns:
        Tuple[str, Optional[str]]: Message and trace ID (if any).
    """
    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, dict):
        message = next(
            (
                str(body[k])
                for k in ("message", "Message", "Error", "error", "title", "detail")
                if body.get(k)
            ),
            "",
        )
        trace_id = body.get("TraceId") or body.get("traceId")
        return message or response.reason or "", trace_id

    text = (response.text or "").strip()
    return (text[:500] or response.reason or ""), None


def _raise_for_response(response: requests.Response) -> None:
    """Raise a descriptive exception for an unsuccessful response.

    Args:
        response: The unsuccessful response.

    Raises:
        SubscriptionKeyError: Missing or invalid subscription key.
        PdmAuthError: Token rejected (401) or access denied (403).
        PdmTimeoutError: Gateway or backend timeout (408/504).
        PdmApiError: Any other error.
    """
    status = response.status_code
    message, trace_id = _error_details(response)
    detail = f"{status} {message}".strip()
    if trace_id:
        detail += f" (TraceId: {trace_id})"

    if _is_key_rejection(response):
        raise SubscriptionKeyError(
            f"The gateway rejected the subscription key: {detail}. If you set "
            f"the key yourself ({ENV_VAR_SUBSCRIPTION_KEY} or "
            "set_subscription_key), check it belongs to the selected "
            "environment; otherwise the key in Key Vault may be outdated.",
            status,
            trace_id,
        )
    if status == 401:
        raise PdmAuthError(
            f"Authentication failed: {detail}. The access token was rejected.",
            status,
            trace_id,
        )
    if status == 403:
        raise PdmAuthError(f"Access denied: {detail}.", status, trace_id)
    if status in (408, 504):
        raise PdmTimeoutError(
            f"The request timed out on the server: {detail}. Narrow the filters "
            "or request fewer columns.",
            status,
            trace_id,
        )
    raise PdmApiError(f"PDM API request failed: {detail}.", status, trace_id)


def _request(
    path: str,
    params: Optional[List[Tuple[str, str]]] = None,
    timeout: Optional[float] = None,
    verbose: bool = False,
) -> requests.Response:
    """Send an authenticated GET request to the API, with retries.

    Retries connection errors and 429/502/503 responses up to
    ``_MAX_RETRIES`` times. Timeouts are not retried, since repeating a slow
    request rarely helps.

    Args:
        path (str): Path relative to the base URL, e.g. ``"api/Ping"``.
        params: Query parameters.
        timeout (Optional[float]): Read timeout in seconds. Defaults to
            ``DEFAULT_TIMEOUT_SECONDS``.
        verbose (bool): Print progress to stdout. Never prints credentials.

    Returns:
        requests.Response: The successful response.

    Raises:
        PdmApiError: Or a subclass, if the request fails.
    """
    env = get_environment()
    url = f"{env.base_url}/{path}"
    key, key_from_vault = _get_subscription_key()
    key_refreshed = False
    read_timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout

    attempt = 0
    while True:
        headers = {
            "Authorization": f"Bearer {get_api_token()}",
            SUBSCRIPTION_KEY_HEADER: key,
        }
        if verbose:
            print(f"GET {path} ({env.name})")
        try:
            response = _get_session().get(
                url,
                params=params,
                headers=headers,
                timeout=(_CONNECT_TIMEOUT_SECONDS, read_timeout),
            )
        except requests.ReadTimeout:
            raise PdmTimeoutError(
                f"No response from the PDM API within {read_timeout:g} s. Narrow "
                "the filters, request fewer columns, or increase timeout."
            ) from None
        except requests.ConnectionError as err:
            if attempt < _MAX_RETRIES:
                delay = _retry_delay(None, attempt)
                if verbose:
                    print(f"Connection failed, retrying in {delay:g} s")
                time.sleep(delay)
                attempt += 1
                continue
            raise PdmApiError(
                f"Could not connect to the PDM API at {env.base_url}: "
                f"{type(err).__name__}: {str(err)[:300]}"
            ) from None

        if response.status_code in _RETRY_STATUS_CODES and attempt < _MAX_RETRIES:
            delay = _retry_delay(response, attempt)
            if verbose:
                print(f"Got {response.status_code}, retrying in {delay:g} s")
            time.sleep(delay)
            attempt += 1
            continue

        # A key from Key Vault may have been rotated since it was cached:
        # read it again once and retry before reporting it as rejected.
        if key_from_vault and not key_refreshed and _is_key_rejection(response):
            if verbose:
                print("Subscription key rejected, reading it again from Key Vault")
            key = _get_key_from_vault(refresh=True)
            key_refreshed = True
            continue

        if not response.ok:
            _raise_for_response(response)
        return response


def _is_key_rejection(response: requests.Response) -> bool:
    """Check whether the gateway rejected the subscription key.

    Args:
        response: A gateway response.

    Returns:
        bool: True for a 401 challenging for an APIM subscription key.
    """
    return response.status_code == 401 and "AzureApiManagementKey" in (
        response.headers.get("WWW-Authenticate", "")
    )


def _parse_json(response: requests.Response) -> Any:
    """Parse a JSON response body.

    Args:
        response: A successful response.

    Returns:
        Any: The decoded JSON.

    Raises:
        PdmApiError: If the body is not valid JSON.
    """
    try:
        return response.json()
    except ValueError:
        raise PdmApiError(
            "The PDM API returned a response that is not valid JSON.",
            response.status_code,
        ) from None


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


def _convert_types(df: pd.DataFrame) -> pd.DataFrame:
    """Convert ISO 8601 date-time string columns to datetime64.

    JSON has no date type, so date-time columns arrive as strings. A column is
    converted only when every non-null value is an ISO 8601 date-time.
    Numbers and booleans are already typed by the JSON decoder.

    Args:
        df: DataFrame built from the JSON records.

    Returns:
        pd.DataFrame: The same DataFrame with date-time columns converted.
    """
    for column in df.columns:
        series = df[column]
        if not (
            pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)
        ):
            continue
        values = series.dropna()
        if values.empty:
            continue
        if all(isinstance(v, str) and _ISO_DATETIME_PATTERN.match(v) for v in values):
            df[column] = pd.to_datetime(series, format="ISO8601")
    return df


def _to_dataframe(records: Any, columns: Optional[List[str]] = None) -> pd.DataFrame:
    """Turn a decoded JSON array of records into a DataFrame.

    Args:
        records: Decoded JSON; must be a list of objects.
        columns: Requested columns, used to shape an empty result.

    Returns:
        pd.DataFrame: The records with converted types.

    Raises:
        PdmApiError: If the JSON is not a list.
    """
    if not isinstance(records, list):
        raise PdmApiError(
            f"Expected a JSON array from the PDM API, got {type(records).__name__}."
        )
    if not records:
        return pd.DataFrame(columns=columns or [])
    return _convert_types(pd.DataFrame.from_records(records))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_api_view(
    resource: str,
    filters: Optional[Dict[str, Any]] = None,
    columns: Optional[Union[str, Sequence[str]]] = None,
    order_by: Optional[Union[str, Sequence[str]]] = None,
    top: Optional[int] = None,
    skip: Optional[int] = None,
    timeout: Optional[float] = None,
    verbose: bool = False,
) -> pd.DataFrame:
    """Read a PDM view through the API and return it as a DataFrame.

    Like :func:`pdm_datareader.query`, all matching rows are returned unless
    ``top`` is given. Access rules per field are the same as in the database.

    Example::

        read_api_view(
            "WellProdDay",
            filters={"COUNTRY": "NO", "PROD_DAY": Range("2022-01-01", "2022-01-31")},
            columns=["PROD_DAY", "WELL_UWI", "ALLOC_OIL_VOL_SM3"],
            order_by="PROD_DAY DESC",
        )

    Args:
        resource (str): View name as in the API, e.g. ``"WellProdDay"``.
        filters (Optional[Dict[str, Any]]): Column name to filter. A value can
            be a plain value (exact match), a list (any of), or a filter helper
            (:class:`Range`, :class:`Like`, :class:`StartsLike`,
            :class:`EndsLike`, :class:`IsNull`, :class:`In`, :class:`Raw`).
        columns (Optional[Union[str, Sequence[str]]]): Columns to return.
            Defaults to all columns.
        order_by (Optional[Union[str, Sequence[str]]]): Sort order, e.g.
            ``"PROD_DAY DESC, WELL_UWI"`` or ``["PROD_DAY DESC", "WELL_UWI"]``.
            Defaults to the API's default order for the view.
        top (Optional[int]): Maximum number of rows. Defaults to all rows.
        skip (Optional[int]): Number of rows to skip. For manual paging, only
            reliable when ``order_by`` uniquely identifies each row; rows
            changed between requests can still shift pages.
        timeout (Optional[float]): Read timeout in seconds. Defaults to
            ``DEFAULT_TIMEOUT_SECONDS``.
        verbose (bool): Print progress to stdout. Defaults to False.

    Returns:
        pd.DataFrame: The matching rows. Date-time columns are converted to
        datetime64.

    Raises:
        ValueError: If an argument is invalid.
        TypeError: If a filter value has an unsupported type.
        SubscriptionKeyError: If the subscription key is missing or rejected.
        PdmAuthError: If authentication or authorization fails.
        PdmTimeoutError: If the request times out.
        PdmApiError: For other API errors.
    """
    _validate_name(resource, "resource name")
    params = _build_params(filters, columns, order_by, top, skip)
    response = _request(
        f"api/flex/{resource}", params=params, timeout=timeout, verbose=verbose
    )
    requested_columns = _split_list(columns) if columns is not None else None
    return _to_dataframe(_parse_json(response), requested_columns)


def ping(timeout: Optional[float] = None) -> Dict[str, Any]:
    """Check the connection to the PDM API.

    Verifies the subscription key, the access token and the API's own
    database connection in one call.

    Args:
        timeout (Optional[float]): Read timeout in seconds.

    Returns:
        Dict[str, Any]: Health information, e.g.
        ``{"Version": "...", "DatabaseCheckPassed": True}``.

    Raises:
        PdmApiError: Or a subclass, if the check fails.
    """
    body = _parse_json(_request("api/Ping", timeout=timeout))
    if not isinstance(body, dict):
        raise PdmApiError(f"Unexpected response from api/Ping: {type(body).__name__}.")
    return body


def user_access(timeout: Optional[float] = None) -> pd.DataFrame:
    """List the fields and facilities the current user has access to.

    Useful for explaining empty results, since rows outside the user's
    access are silently filtered out.

    Args:
        timeout (Optional[float]): Read timeout in seconds.

    Returns:
        pd.DataFrame: One row per accessible field/facility.

    Raises:
        PdmApiError: Or a subclass, if the request fails.
    """
    body = _parse_json(_request("api/UserAccess", timeout=timeout))
    if isinstance(body, dict):
        body = [body]
    return _to_dataframe(body)
