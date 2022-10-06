import struct
import sys
from typing import Any, List, Optional

import msal
import pandas as pd
import pyodbc
from msal_extensions import *

from pdm_tools.utils import get_login_name


def query(sql: str,
          params: Optional[List[Any]] = None,
          short_name: Optional[str] = get_login_name(),
          verbose: Optional[bool] = True):
    # SHORTNAME@equinor.com -- short name shall be capitalized
    username = short_name.upper()+'@equinor.com'
    tenantID = '3aa4a235-b6e2-48d5-9195-7fcf05b459b0'
    authority = 'https://login.microsoftonline.com/' + tenantID
    clientID = '9ed0d36d-1034-475a-bdce-fa7b774473fb'
    scopes = ['https://database.windows.net/.default']
    result = None
    accounts = None
    myAccount = None
    idTokenClaims = None

    def msal_persistence(location, fallback_to_plaintext=False):
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

    def connect_to_db(result):
        global conn

        try:
            # Request
            SQL_COPT_SS_ACCESS_TOKEN = 1256
            server = 'pdmprod.database.windows.net'
            database = "pdm"
            driver = 'ODBC Driver 18 for SQL Server'
            connection_string = 'DRIVER='+driver+';SERVER='+server+';DATABASE='+database

            # get bytes from token obtained
            tokenb = bytes(result['access_token'], 'UTF-8')
            exptoken = b''
            for i in tokenb:
                exptoken += bytes({i})
                exptoken += bytes(1)

            tokenstruct = struct.pack("=i", len(exptoken)) + exptoken
            if verbose:
                print('Connecting to Database')
            conn = pyodbc.connect(connection_string, attrs_before={
                                  SQL_COPT_SS_ACCESS_TOKEN: tokenstruct})
        except pyodbc.ProgrammingError as pe:
            if "(40615) (SQLDriverConnect)" in repr(pe):
                if verbose:
                    print(
                        "Fails connecting from current IP-address. Are you on Equinor network?")
                raise
            if verbose:
                print('Connection to db failed: ', err)
        except pyodbc.InterfaceError as pe:
            if "(18456) (SQLDriverConnect)" in repr(pe):
                if verbose:
                    print("Login using token failed. Do you have access?")
                raise
            if verbose:
                print('Connection to db failed: ', err)
        except Exception as err:
            if verbose:
                print('Connection to db failed: ', err)

    accounts = msal_cache_accounts(clientID, authority)

    if accounts:
        for account in accounts:
            if account['username'] == username:
                myAccount = account
                if verbose:
                    print("Found account in MSAL Cache: " + account['username'])
                    print("Attempting to obtain a new Access Token using the Refresh Token")
                result = msal_delegated_refresh(
                    clientID, scopes, authority, myAccount)

                if result is None:
                    # Get a new Access Token using the Interactive Flow
                    if verbose:
                        print("Interactive Authentication required to obtain a new Access Token.")
                    result = msal_delegated_interactive_flow(
                        scopes=scopes, domain_hint=tenantID)
    else:
        # No accounts found in the local MSAL Cache
        # Trigger interactive authentication flow
        if verbose:
            print("First authentication")
        result = msal_delegated_interactive_flow(
            scopes=scopes, domain_hint=tenantID)
        idTokenClaims = result['id_token_claims']
        username = idTokenClaims['preferred_username']

    if result:
        if result["access_token"]:
            connect_to_db(result)

            #  Query Database
            if verbose:
                print('Querying database')

            df = pd.read_sql(sql, conn, params=params)
            return df
    else:
        print(f'Received no data. '
              f'This may be due to the account retrieved not having sufficient access or not existing. '
              f'The shortname used was: {short_name} ')
