import hashlib
import struct
import time
from typing import Optional

import pandas as pd
import sqlalchemy.exc

from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.engine import URL

from msal_bearer import BearerAuth, get_user_name


# Maximum lifetime of a cached engine, in seconds. Kept below the typical
# Azure AD access token lifetime (~60 min) so an expired token is not reused.
_ENGINE_TTL_SECONDS = 30 * 60

_engine = None
_engine_token = None
_engine_created_at = 0.0
_token = ""
_user_name = ""


def _token_key(tokenstruct) -> Optional[str]:
    """Derive a non-reversible key identifying a token struct.

    Used to detect when the cached engine belongs to a different identity
    without keeping the raw access token in memory.

    Args:
        tokenstruct: Packed access token struct, or None.

    Returns:
        Optional[str]: A hex digest of the token, or None if no token.
    """
    if tokenstruct is None:
        return None
    return hashlib.sha256(tokenstruct).hexdigest()


def set_token(token: str):
    """Setter for token if not using user-impersonation.

    Args:
        token (str): Authentication token string to use.
    """
    global _token
    _token = token


def get_token(username: str = "") -> str:
    """Getter for authentication token. Will return auth token using user-impersonation if no token is set using set_token.

    Args:
        username (str, optional): User name (email address) of user to get token for.

    Returns:
        str: Authentication token string
    """

    if not _token:
        global _user_name

        if not username:
            if not _user_name:
                _user_name = get_user_name()
            username = _user_name
        else:
            _user_name = username

        # SHORTNAME@equinor.com -- short name shall be capitalized
        username = username.upper()  # Also capitalize equinor.com
        if not username.endswith("@EQUINOR.COM"):
            username = username + "@EQUINOR.COM"

        tenantID = "3aa4a235-b6e2-48d5-9195-7fcf05b459b0"
        clientID = "9ed0d36d-1034-475a-bdce-fa7b774473fb"
        scopes = ["https://database.windows.net/.default"]
        auth = BearerAuth.get_auth(
            tenantID=tenantID, clientID=clientID, scopes=scopes, username=username
        )
        return auth.token

    return _token


def get_engine(conn_url: str = "", tokenstruct: Optional[bytes] = None, reset: bool = False) -> "sqlalchemy.engine.Engine":
    """Get a cached SQLAlchemy engine, creating one if needed.

    The engine is cached at module level and scoped to the token it was
    created with. It is rebuilt automatically when ``reset`` is True, when
    ``tokenstruct`` differs from the token of the cached engine, or when the
    cached engine is older than ``_ENGINE_TTL_SECONDS`` (to avoid reusing an
    expired access token).

    Args:
        conn_url (str, optional): ODBC connection string used to build the
            engine when a new one is created. Defaults to "".
        tokenstruct (optional): Packed access token struct passed to the driver
            via ``attrs_before``. Defaults to None.
        reset (bool, optional): Force disposal of any existing engine before
            returning. Defaults to False.

    Returns:
        sqlalchemy.engine.Engine: The cached or newly created engine.
    """
    global _engine, _engine_token, _engine_created_at

    if reset:
        reset_engine()

    # Rebuild the engine if it was created for a different token (identity),
    # including transitions to or from None. The token is baked into the
    # connection via attrs_before, so reusing a cached engine across identities
    # would run queries under the wrong user.
    if _engine is not None and _token_key(tokenstruct) != _engine_token:
        reset_engine()

    # Rebuild the engine once it exceeds its TTL so a stale, likely-expired
    # token is not reused for new connections.
    if (
        _engine is not None
        and time.monotonic() - _engine_created_at > _ENGINE_TTL_SECONDS
    ):
        reset_engine()

    if _engine is None:
        SQL_COPT_SS_ACCESS_TOKEN = 1256
        _engine = create_engine(
            URL.create("mssql+pyodbc", query={"odbc_connect": conn_url}),
            connect_args={"attrs_before": {SQL_COPT_SS_ACCESS_TOKEN: tokenstruct}},
        )
        _engine_token = _token_key(tokenstruct)
        _engine_created_at = time.monotonic()

    return _engine


def reset_engine():
    """Reset connection engine"""
    global _engine, _engine_token, _engine_created_at

    if _engine is not None:
        _engine.dispose()
        _engine = None

    _engine_token = None
    _engine_created_at = 0.0


def connect_to_db(token, verbose=False):
    try:
        # Request
        server = "pdmprod.database.windows.net"
        database = "pdm"
        driver = "ODBC Driver 18 for SQL Server"  # Primary driver if available
        driver_fallback = (
            "ODBC Driver 17 for SQL Server"  # Fallback driver if available
        )
        connection_string = f"DRIVER={driver};SERVER={server};DATABASE={database}"
        connection_string_fallback = (
            f"DRIVER={driver_fallback};SERVER={server};DATABASE={database}"
        )

        # get bytes from token obtained
        tokenb = bytes(token, "UTF-8")
        exptoken = b""
        for i in tokenb:
            exptoken += bytes({i})
            exptoken += bytes(1)

        tokenstruct = struct.pack("=i", len(exptoken)) + exptoken
        if verbose:
            print("Connecting to Database")
        try:
            conn = get_engine(connection_string, tokenstruct).connect()
        except sqlalchemy.exc.InterfaceError as pe:
            if "no default driver specified" in repr(pe):
                conn = get_engine(
                    connection_string_fallback, tokenstruct, reset=True
                ).connect()
            else:
                raise
        except sqlalchemy.exc.DBAPIError as pe:
            if (
                "[unixODBC][Driver Manager]Can" in repr(pe)
                and "open lib" in repr(pe)
                and driver in repr(pe)
            ):
                conn = get_engine(
                    connection_string_fallback, tokenstruct, reset=True
                ).connect()
            else:
                raise
    except sqlalchemy.exc.ProgrammingError as pe:
        reset_engine()
        if "(40615) (SQLDriverConnect)" in repr(pe):
            if verbose:
                print(
                    "Fails connecting from current IP-address. Are you on Equinor network?"
                )
        if verbose:
            print("Connection to db failed: ", pe)
        raise
    except sqlalchemy.exc.InterfaceError as pe:
        reset_engine()
        if "(18456) (SQLDriverConnect)" in repr(pe):
            if verbose:
                print("Login using token failed. Do you have access?")
        elif verbose:
            print("Connection to db failed: ", pe)
        raise
    except Exception as err:
        reset_engine()
        if verbose:
            print("Connection to db failed: ", err)
        raise

    return conn


def query(
    sql: str,
    params: Optional[dict] = None,
    verbose: Optional[bool] = False,
) -> pd.DataFrame:
    """
    Wrapper to pd.read_sql. Query database and get result as pd.DataFrame.

    Security:
        Always pass user-supplied values through ``params`` so they are bound
        as SQL parameters. Never build ``sql`` by string-formatting or
        concatenating untrusted input, as this exposes the query to SQL
        injection.

        Safe::

            query("SELECT * FROM t WHERE id = :id", params={"id": user_id})

        Unsafe::

            query(f"SELECT * FROM t WHERE id = {user_id}")

    Args:
        sql (str): SQL query to run. Use bind parameters (e.g. ``:name``) for
            any dynamic values instead of string interpolation.
        params (Optional[dict], optional): SQL parameters as dictionary. Defaults to None.
        verbose (Optional[bool], optional): Set true to print debugging log to stdout. Defaults to False.

    Returns:
        pd.DataFrame: Table contents returned from pd.read_sql
    """

    stmt = sql_text(sql)
    if params:
        stmt = stmt.bindparams(**params)

    with connect_to_db(get_token(), verbose=verbose) as connection:
        #  Query Database
        if verbose:
            print("Querying database")
        return pd.read_sql(stmt, connection)
