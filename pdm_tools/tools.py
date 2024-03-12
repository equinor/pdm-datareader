import struct
from typing import Optional

import pandas as pd
import sqlalchemy.exc

from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.engine import URL

from msal_bearer.BearerAuth import BearerAuth, get_login_name

engine = None

def reset_engine():
    global engine

    if engine is not None:
        engine.dispose()
        engine = None

def query(
    sql: str,
    params: Optional[dict] = None,
    short_name: Optional[str] = get_login_name(),
    verbose: Optional[bool] = False,
):
    # SHORTNAME@equinor.com -- short name shall be capitalized
    username = short_name.upper() + "@equinor.com"
    tenantID = "3aa4a235-b6e2-48d5-9195-7fcf05b459b0"
    clientID = "9ed0d36d-1034-475a-bdce-fa7b774473fb"
    scopes = ["https://database.windows.net/.default"]

    def connection_url(conn_string):
        conn_url = URL.create("mssql+pyodbc", query={"odbc_connect": conn_string})
        return conn_url

    def get_engine(conn_url="", tokenstruct=None):
        global engine

        SQL_COPT_SS_ACCESS_TOKEN = 1256

        if engine is None:
            engine = create_engine(
                connection_url(conn_url),
                connect_args={"attrs_before": {SQL_COPT_SS_ACCESS_TOKEN: tokenstruct}},
            )

        return engine

    def connect_to_db(token):
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
                reset_engine()
                if "no default driver specified" in repr(pe):
                    conn = get_engine(connection_string_fallback, tokenstruct).connect()
                else:
                    raise
            except sqlalchemy.exc.DBAPIError as pe:
                reset_engine()
                if "[unixODBC][Driver Manager]Can't open lib" in repr(pe):
                    conn = get_engine(connection_string_fallback, tokenstruct).connect()
                else:
                    raise
        except sqlalchemy.exc.ProgrammingError as pe:
            reset_engine()
            if "(40615) (SQLDriverConnect)" in repr(pe):
                if verbose:
                    print(
                        "Fails connecting from current IP-address. Are you on Equinor network?"
                    )
                raise
            if verbose:
                print("Connection to db failed: ", pe)
        except sqlalchemy.exc.InterfaceError as pe:
            reset_engine()
            if "(18456) (SQLDriverConnect)" in repr(pe):
                if verbose:
                    print("Login using token failed. Do you have access?")
                raise
            if verbose:
                print("Connection to db failed: ", pe)
                raise
        except Exception as err:
            reset_engine()
            if verbose:
                print("Connection to db failed: ", err)
                raise

        return conn

    try:
        auth = BearerAuth.get_auth(
            tenantID=tenantID, clientID=clientID, scopes=scopes, username=username
        )
        conn = connect_to_db(auth.token)

        #  Query Database
        if verbose:
            print("Querying database")

        with conn as connection:
            df = pd.read_sql(sql_text(sql), connection, params=params)

        return df
    except:
        print(
            f"Received no data. "
            f"This may be due to the account retrieved not having sufficient access or not existing. "
            f"The shortname used was: {short_name} "
        )
