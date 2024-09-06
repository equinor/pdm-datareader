import struct
from typing import Optional

import pandas as pd
import sqlalchemy.exc

from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.engine import URL

from msal_bearer.BearerAuth import BearerAuth, get_login_name

_engine = None
_token = ""
_user_name = ""


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
                _user_name = get_login_name()
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


def get_engine(conn_url: str = "", tokenstruct=None, reset: bool = False):
    global _engine

    if reset:
        reset_engine()

    if _engine is None:
        SQL_COPT_SS_ACCESS_TOKEN = 1256
        _engine = create_engine(
            URL.create("mssql+pyodbc", query={"odbc_connect": conn_url}),
            connect_args={"attrs_before": {SQL_COPT_SS_ACCESS_TOKEN: tokenstruct}},
        )

    return _engine


def reset_engine():
    """Reset connection engine"""
    global _engine

    if _engine is not None:
        _engine.dispose()
        _engine = None


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
    """Wrapper to pd.read_sql. Query database and get result as pd.DataFrame

    Args:
        sql (str): SQL query to run
        params (Optional[dict], optional): SQL parameters as dictionary. Defaults to None.
        verbose (Optional[bool], optional): Set true to print debugging log to stdout. Defaults to False.

    Returns:
        pd.DataFrame: Table contents returned from pd.read_sql
    """

    with connect_to_db(get_token(), verbose=verbose) as connection:
        #  Query Database
        if verbose:
            print("Querying database")
        return pd.read_sql(sql_text(sql), connection, params=params)
