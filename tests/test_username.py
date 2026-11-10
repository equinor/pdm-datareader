import pytest

from pdm_datareader import tools


@pytest.mark.parametrize(
    "username",
    [
        "",
        "abc",
        "ABC",
        "AbC",
        "abc@equinor.com",
        "ABC@EQUINOR.COM",
        "AbC@Equinor.com",
    ],
)
def test_provide_user_name(username: str, monkeypatch: pytest.MonkeyPatch):
    detected_users = []
    requested_users = []

    class AuthResult:
        token = "test-token"

    def get_user_name():
        detected_users.append("abc")
        return "abc"

    def get_auth(*, tenantID, clientID, scopes, username):
        requested_users.append(username)
        return AuthResult()

    monkeypatch.setattr(tools, "_token", "")
    monkeypatch.setattr(tools, "_user_name", "")
    monkeypatch.setattr(tools, "get_user_name", get_user_name)
    monkeypatch.setattr(tools.BearerAuth, "get_auth", get_auth)

    assert tools.get_token(username=username) == "test-token"

    assert requested_users == ["ABC@EQUINOR.COM"]
    assert detected_users == ([] if username else ["abc"])
