import pytest

from pdm_datareader import tools


@pytest.fixture(autouse=True)
def reset_state():
    """Ensure a clean engine cache before and after each test."""
    tools.reset_engine()
    tools.set_token("")
    yield
    tools.reset_engine()
    tools.set_token("")


def test_engine_is_cached_for_same_token():
    token = b"token-a"
    engine1 = tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=token)
    engine2 = tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=token)

    assert engine1 is engine2


def test_engine_rebuilt_for_different_token():
    engine_a = tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=b"token-a")
    engine_b = tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=b"token-b")

    # A different identity must not reuse the cached engine.
    assert engine_a is not engine_b


def test_engine_rebuilt_on_none_transition():
    # None -> token and token -> None must both rebuild the engine.
    engine_none = tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=None)
    engine_token = tools.get_engine(
        "DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=b"token-a"
    )
    engine_none_again = tools.get_engine(
        "DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=None
    )

    assert engine_none is not engine_token
    assert engine_token is not engine_none_again


def test_engine_token_is_not_stored_raw():
    token = b"super-secret-token"
    tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=token)

    # Only a derived digest should be kept, never the raw token bytes.
    assert tools._engine_token != token
    assert tools._engine_token == tools._token_key(token)


def test_engine_rebuilt_after_ttl_expiry(monkeypatch):
    token = b"token-a"
    engine1 = tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=token)

    # Simulate time passing beyond the engine TTL.
    monkeypatch.setattr(
        tools, "_engine_created_at", tools._engine_created_at - tools._ENGINE_TTL_SECONDS - 1
    )
    engine2 = tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=token)

    assert engine1 is not engine2



def test_reset_engine_clears_cache():
    token = b"token-a"
    engine1 = tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=token)
    tools.reset_engine()
    engine2 = tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=token)

    assert engine1 is not engine2


def test_reset_flag_rebuilds_engine():
    token = b"token-a"
    engine1 = tools.get_engine("DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=token)
    engine2 = tools.get_engine(
        "DRIVER=x;SERVER=y;DATABASE=z", tokenstruct=token, reset=True
    )

    assert engine1 is not engine2


def test_set_token_returned_by_get_token():
    tools.set_token("my-explicit-token")
    assert tools.get_token() == "my-explicit-token"
