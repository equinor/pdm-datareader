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
