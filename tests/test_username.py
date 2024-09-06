from msal_bearer.BearerAuth import get_login_name
from pdm_datareader.tools import get_token


def test_provide_user_name():
    user_name = get_login_name()
    b_0 = get_token()
    assert b_0 == get_token(username=user_name)
    assert b_0 == get_token(username=user_name.upper())
    assert b_0 == get_token(username=user_name.lower())
    assert b_0 == get_token(username=user_name.lower() + "@equinor.com")
