import struct
import sys
from typing import Any, List, Optional

import msal
import pandas as pd
import sqlalchemy.exc
from msal_extensions import *
from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.engine import URL

from pdm_tools.utils import get_login_name

engine = None

def reset_engine():
    global engine
    
    if engine is not None:
        engine.dispose()
        engine = None

def query(sql: str,
          params: Optional[List[Any]] = None,
          short_name: Optional[str] = get_login_name(),
          verbose: Optional[bool] = False):

    # SHORTNAME@equinor.com -- short name shall be capitalized
    username = short_name.upper()+'@equinor.com'
    tenantID = '3aa4a235-b6e2-48d5-9195-7fcf05b459b0'
    authority = 'https://login.microsoftonline.com/' + tenantID
    clientID = '9ed0d36d-1034-475a-bdce-fa7b774473fb'
    scopes = ['https://database.windows.net/.default']
    result = None
    accounts = None
    myAccount = None

    def msal_persistence(location):
        """Build a suitable persistence instance based your current OS"""
        if sys.platform.startswith('win'):
            return FilePersistenceWithDataProtection(location)
        if sys.platform.startswith('darwin'):
            return KeychainPersistence(location, "my_service_name", "my_account_name")
        return FilePersistence(location)

    def msal_cache_accounts(clientID, authority):
        # Accounts
        persistence = msal_persistence("token_cache.bin")
        if verbose:
            print("Is this MSAL persistence cache encrypted?",
                  persistence.is_encrypted)
        cache = PersistedTokenCache(persistence)

        app = msal.PublicClientApplication(
            client_id=clientID, authority=authority, token_cache=cache)
        accounts = app.get_accounts()
        return accounts

    def msal_delegated_interactive_flow(scopes, prompt=None, login_hint=None, domain_hint=None):
        persistence = msal_persistence("token_cache.bin")
        cache = PersistedTokenCache(persistence)
        app = msal.PublicClientApplication(
            clientID, authority=authority, token_cache=cache)
        result = app.acquire_token_interactive(
            scopes=scopes, prompt=prompt, login_hint=login_hint, domain_hint=domain_hint)
        return result

    def msal_delegated_refresh(clientID, scopes, authority, account):
        persistence = msal_persistence("token_cache.bin")
        cache = PersistedTokenCache(persistence)

        app = msal.PublicClientApplication(
            client_id=clientID, authority=authority, token_cache=cache)
        result = app.acquire_token_silent_with_error(
            scopes=scopes, account=account)
        return result

    def connection_url(conn_string):
        conn_url = URL.create(
            'mssql+pyodbc',
            query={
                'odbc_connect': conn_string
            }
        )
        return conn_url

    def get_engine(conn_url="", tokenstruct=None):
        global engine

        SQL_COPT_SS_ACCESS_TOKEN = 1256

        if engine is None:
            engine = create_engine(
                connection_url(conn_url),
                connect_args={
                    'attrs_before': {
                        SQL_COPT_SS_ACCESS_TOKEN: tokenstruct
                    }
                }
            )

        return engine

    def connect_to_db(result):
        try:
            # Request
            server = 'pdmprod.database.windows.net'
            database = "pdm"
            driver = 'ODBC Driver 18 for SQL Server'  # Primary driver if available
            driver_fallback = 'ODBC Driver 17 for SQL Server'  # Fallback driver if available
            connection_string = f"DRIVER={driver};SERVER={server};DATABASE={database}"
            connection_string_fallback = f"DRIVER={driver_fallback};SERVER={server};DATABASE={database}"

            # get bytes from token obtained
            tokenb = bytes(result['access_token'], 'UTF-8')
            exptoken = b''
            for i in tokenb:
                exptoken += bytes({i})
                exptoken += bytes(1)

            tokenstruct = struct.pack("=i", len(exptoken)) + exptoken
            if verbose:
                print('Connecting to Database')
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
                        "Fails connecting from current IP-address. Are you on Equinor network?")
                raise
            if verbose:
                print('Connection to db failed: ', pe)
        except sqlalchemy.exc.InterfaceError as pe:
            reset_engine()
            if "(18456) (SQLDriverConnect)" in repr(pe):
                if verbose:
                    print("Login using token failed. Do you have access?")
                raise
            if verbose:
                print('Connection to db failed: ', pe)
                raise
        except Exception as err:
            reset_engine()
            if verbose:
                print('Connection to db failed: ', err)
                raise

        return conn

    accounts = msal_cache_accounts(clientID, authority)

    if accounts:
        for account in accounts:
            if account['username'] == username:
                myAccount = account
                if verbose:
                    print(
                        f"Found account in MSAL Cache: {account['username']}")
                    print(
                        "Attempting to obtain a new Access Token using the Refresh Token")
                result = msal_delegated_refresh(
                    clientID, scopes, authority, myAccount)

                if not "access_token" in result:
                    # Get a new Access Token using the Interactive Flow
                    if verbose:
                        print(
                            "Interactive Authentication required to obtain a new Access Token.")
                    reset_engine()
                    result = msal_delegated_interactive_flow(
                        scopes=scopes, domain_hint=tenantID)
    else:
        # No accounts found in the local MSAL Cache
        # Trigger interactive authentication flow
        if verbose:
            print("First authentication")
        
        reset_engine()
        result = msal_delegated_interactive_flow(
            scopes=scopes, domain_hint=tenantID)

    if result:
        if "access_token" in result:
            conn = connect_to_db(result)

            #  Query Database
            if verbose:
                print('Querying database')

            with conn as connection:
                df = pd.read_sql(sql_text(sql), connection, params=params)

            return df
        else:
            print(f"Failed getting token, returned:\n{result}")
    else:
        print(f'Received no data. '
              f'This may be due to the account retrieved not having sufficient access or not existing. '
              f'The shortname used was: {short_name} ')
