"""Mocked tests for the PDM API client (pdm_datareader.api).

No real credentials or network are used: token acquisition is replaced by a
fake ``BearerAuth``, every HTTP request goes through ``responses`` (unmatched
requests fail instead of reaching the network), and ``time.sleep`` is recorded
instead of waiting.
"""

import base64
import datetime as dt
import json
from decimal import Decimal
from email.utils import format_datetime
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit

import numpy as np
import pandas as pd
import pytest
import requests
import responses

import pdm_datareader as pdm
from pdm_datareader import api
from pdm_datareader.api import (
    EndsLike,
    In,
    IsNull,
    Like,
    PdmApiError,
    PdmAuthError,
    PdmTimeoutError,
    Range,
    Raw,
    StartsLike,
    SubscriptionKeyError,
)

BASE = api.ENVIRONMENTS["prod"].base_url
TEST_BASE = api.ENVIRONMENTS["test"].base_url
OTHER_HOST = "http://other.example/collect"
FAKE_UPN = "user@equinor.com"
SENTINEL_TOKEN = "sentinel-token-that-must-not-appear"
SENTINEL_KEY = "sentinel-key-that-must-not-appear"

KEY_REJECTED = dict(
    status=401,
    headers={"WWW-Authenticate": 'AzureApiManagementKey realm="x"'},
    json={"statusCode": 401, "message": "Access denied due to invalid key."},
)
TOKEN_REJECTED = dict(
    status=401,
    headers={"WWW-Authenticate": "Bearer"},
    json={"Error": "Unauthorized", "StatusCode": 401, "TraceId": "t-401"},
)
PING_OK = {"version": "3.0", "databaseCheckPassed": True}


def fake_jwt(**claims) -> str:
    """Build an unsigned JWT-shaped string carrying ``claims``."""

    def enc(data: dict) -> str:
        raw = json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{enc({'alg': 'none'})}.{enc(claims)}.signature"


class FakeAuth:
    """Records token requests and returns fake JWTs instead of calling Azure AD."""

    def __init__(self):
        self.calls = []
        self.upn = FAKE_UPN

    def get_auth(self, tenantID, clientID, scopes, username="", **kwargs):
        self.calls.append(
            SimpleNamespace(
                tenant=tenantID, client_id=clientID, scope=scopes[0], username=username
            )
        )
        return SimpleNamespace(token=self.token_for(scopes[0]))

    def token_for(self, scope: str) -> str:
        return fake_jwt(upn=self.upn, aud=scope)

    def scopes(self):
        return [c.scope for c in self.calls]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Reset module state, block network and fake auth for every test."""
    for name in (
        api.ENV_VAR_ENVIRONMENT,
        api.ENV_VAR_BASE_URL,
        api.ENV_VAR_CLIENT_ID,
        api.ENV_VAR_SUBSCRIPTION_KEY,
    ):
        monkeypatch.delenv(name, raising=False)

    api._reset_session()
    monkeypatch.setattr(api, "_environment_name", "")
    monkeypatch.setattr(api, "_api_token", "")
    monkeypatch.setattr(api, "_api_user_name", "")
    monkeypatch.setattr(api, "_subscription_key", "")
    yield
    api._reset_session()


@pytest.fixture(autouse=True)
def auth(monkeypatch):
    fake = FakeAuth()
    monkeypatch.setattr(
        api, "BearerAuth", SimpleNamespace(get_auth=fake.get_auth), raising=True
    )
    return fake


@pytest.fixture(autouse=True)
def http():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(api.time, "sleep", recorded.append)
    return recorded


@pytest.fixture
def key():
    """Use an explicit subscription key."""
    api.set_subscription_key("sub-key-123")
    return "sub-key-123"


def query_params(call):
    return parse_qsl(urlsplit(call.request.url).query, keep_blank_values=True)


def api_calls(http):
    return [c for c in http.calls if c.request.url.startswith(BASE)]


# ---------------------------------------------------------------------------
# Filter and request serialization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("NO", "NO"),
        (5, "5"),
        (2.5, "2.5"),
        (True, "true"),
        (False, "false"),
        (Decimal("1.10"), "1.10"),
        (np.int64(7), "7"),
        (np.float64(1.5), "1.5"),
        (np.bool_(True), "true"),
        (dt.date(2024, 1, 2), "2024-01-02T00:00:00"),
        (dt.datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05"),
        (pd.Timestamp("2024-01-02 03:04:05"), "2024-01-02T03:04:05"),
        (np.datetime64("2024-01-02T03:04:05"), "2024-01-02T03:04:05"),
        (["a", "b"], "[a, b]"),
        ((1, 2), "[1, 2]"),
        (Range(1, 5), "RANGE(1 | 5)"),
        (Range(1), "RANGE(1 |)"),
        (Range(end=5), "RANGE(| 5)"),
        (
            Range(dt.date(2024, 1, 1), dt.date(2024, 1, 31)),
            "RANGE(2024-01-01T00:00:00 | 2024-01-31T00:00:00)",
        ),
        (Like("F-1"), "LIKE(F-1)"),
        (StartsLike("JOHAN"), "STARTS_LIKE(JOHAN)"),
        (EndsLike("SVERDRUP"), "ENDS_LIKE(SVERDRUP)"),
        (IsNull(), "ISNULL()"),
        (In([Range(2, 5), 7]), "[RANGE(2 | 5), 7]"),
        (In(["a", Like("b")]), "[a, LIKE(b)]"),
        (Raw("RANGE(2 | 5)"), "RANGE(2 | 5)"),
    ],
)
def test_filter_value_rendering(value, expected):
    assert api._filter_param(value) == expected


@pytest.mark.parametrize("char", list('|,[]()"'))
@pytest.mark.parametrize("wrap", [str, Like, StartsLike, EndsLike, lambda v: In([v])])
def test_reserved_characters_are_rejected(char, wrap):
    with pytest.raises(ValueError, match="reserved character"):
        api._filter_param(wrap(f"a{char}b"))


@pytest.mark.parametrize(
    "make, error",
    [
        (lambda: api._filter_param(None), TypeError),
        (lambda: api._filter_param(object()), TypeError),
        (lambda: api._filter_param(""), ValueError),
        (lambda: api._filter_param(float("nan")), ValueError),
        (lambda: api._filter_param(float("inf")), ValueError),
        (lambda: api._filter_param(Decimal("NaN")), ValueError),
        (
            lambda: api._filter_param(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)),
            ValueError,
        ),
        (lambda: Range(), ValueError),
        (lambda: In([]), ValueError),
        (lambda: In("abc"), TypeError),
        (lambda: In([In([1])]), TypeError),
        (lambda: Like(5).to_param(), TypeError),
        (lambda: Raw(""), ValueError),
    ],
)
def test_invalid_filter_values(make, error):
    with pytest.raises(error):
        make()


def test_top_all_is_sent_when_top_is_omitted():
    # The API returns only 1000 rows without Top, so ALL must be explicit.
    assert api._build_params(None, None, None, None, None) == [("Top", "ALL")]


def test_top_skip_columns_order_by_and_filters_are_serialized():
    params = api._build_params(
        filters={"COUNTRY": "NO", "PROD_DAY": Range(dt.date(2024, 1, 1))},
        columns="PROD_DAY, WELL_UWI",
        order_by=["PROD_DAY desc", "WELL_UWI"],
        top=10,
        skip=20,
    )
    assert params == [
        ("Top", "10"),
        ("Skip", "20"),
        ("Columns", "PROD_DAY,WELL_UWI"),
        ("OrderBy", "PROD_DAY DESC,WELL_UWI"),
        ("COUNTRY", "NO"),
        ("PROD_DAY", "RANGE(2024-01-01T00:00:00 |)"),
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"top": 0},
        {"top": -1},
        {"top": 1.5},
        {"top": True},
        {"skip": -1},
        {"skip": "10"},
        {"columns": []},
        {"columns": ["PROD_DAY", "BAD NAME"]},
        {"order_by": "PROD_DAY; DROP TABLE x"},
        {"order_by": "PROD_DAY SIDEWAYS"},
        {"order_by": []},
        {"filters": {"Top": 1}},
        {"filters": {"orderBy": "x"}},
        {"filters": {"BAD-NAME": 1}},
    ],
)
def test_invalid_request_arguments(kwargs):
    args = {"filters": None, "columns": None, "order_by": None, "top": None}
    args.update({"skip": None}, **kwargs)
    with pytest.raises(ValueError):
        api._build_params(**args)


@pytest.mark.parametrize("name", ["PDMVW.WELL_PROD_DAY", "Well Prod Day", "../x", ""])
def test_invalid_resource_name_is_rejected_before_any_request(http, key, auth, name):
    with pytest.raises(ValueError):
        pdm.read_api_view(name)
    assert len(http.calls) == 0
    assert auth.calls == []


def test_read_api_view_sends_expected_request(http, key, auth):
    http.get(f"{BASE}/api/flex/WellProdDay", json=[])

    pdm.read_api_view(
        "WellProdDay",
        filters={
            "COUNTRY": "NO",
            "PROD_DAY": Range(dt.date(2024, 1, 1), dt.date(2024, 1, 31)),
            "WELL_UWI": ["A", "B"],
        },
        columns=["PROD_DAY", "WELL_UWI"],
        order_by="PROD_DAY DESC, WELL_UWI",
    )

    (call,) = http.calls
    assert urlsplit(call.request.url).path.endswith("/api/flex/WellProdDay")
    assert query_params(call) == [
        ("Top", "ALL"),
        ("Columns", "PROD_DAY,WELL_UWI"),
        ("OrderBy", "PROD_DAY DESC,WELL_UWI"),
        ("COUNTRY", "NO"),
        ("PROD_DAY", "RANGE(2024-01-01T00:00:00 | 2024-01-31T00:00:00)"),
        ("WELL_UWI", "[A, B]"),
    ]
    headers = call.request.headers
    assert headers["Authorization"] == "Bearer " + auth.token_for(
        api.ENVIRONMENTS["prod"].scope
    )
    assert headers[api.SUBSCRIPTION_KEY_HEADER] == key
    assert headers["User-Agent"].startswith("pdm-datareader/")
    # Credentials travel in headers only, never in the URL.
    assert key not in call.request.url


# ---------------------------------------------------------------------------
# DataFrame conversion
# ---------------------------------------------------------------------------


def test_response_is_converted_to_typed_dataframe(http, key):
    http.get(
        f"{BASE}/api/flex/WellProdDay",
        json=[
            {
                "PROD_DAY": "2024-01-01T00:00:00",
                "DWH_TIMESTAMP": "2021-11-19T16:19:32.7133333",
                "WELL_UWI": "A",
                "OIL": 1.5,
                "HOURS": 24,
                "ACTIVE": True,
            },
            {
                "PROD_DAY": None,
                "DWH_TIMESTAMP": "2021-11-19T16:19:33",
                "WELL_UWI": "B",
                "OIL": None,
                "HOURS": 12,
                "ACTIVE": False,
            },
        ],
    )

    df = pdm.read_api_view("WellProdDay")

    assert pd.api.types.is_datetime64_any_dtype(df["PROD_DAY"])
    assert pd.api.types.is_datetime64_any_dtype(df["DWH_TIMESTAMP"])
    assert df["PROD_DAY"].iloc[0] == pd.Timestamp("2024-01-01")
    assert pd.isna(df["PROD_DAY"].iloc[1])
    assert pd.api.types.is_float_dtype(df["OIL"])
    assert pd.isna(df["OIL"].iloc[1])
    assert pd.api.types.is_integer_dtype(df["HOURS"])
    assert pd.api.types.is_bool_dtype(df["ACTIVE"])
    assert list(df["WELL_UWI"]) == ["A", "B"]
    assert not pd.api.types.is_datetime64_any_dtype(df["WELL_UWI"])


def test_column_with_non_date_strings_is_not_converted(http, key):
    http.get(
        f"{BASE}/api/flex/View",
        json=[{"CODE": "2024-01-01T00:00:00"}, {"CODE": "not a date"}],
    )
    df = pdm.read_api_view("View")
    assert not pd.api.types.is_datetime64_any_dtype(df["CODE"])
    assert list(df["CODE"]) == ["2024-01-01T00:00:00", "not a date"]


def test_all_null_column_stays_object(http, key):
    http.get(f"{BASE}/api/flex/View", json=[{"A": None}, {"A": None}])
    df = pdm.read_api_view("View")
    assert df["A"].isna().all()


def test_utf8_values_are_decoded(http, key):
    http.get(
        f"{BASE}/api/flex/View",
        body='[{"GOV_FCTY_NAME": "ÅSGARD B"}]'.encode("utf-8"),
        content_type="application/json; charset=utf-8",
    )
    df = pdm.read_api_view("View")
    assert df["GOV_FCTY_NAME"].iloc[0] == "ÅSGARD B"


def test_empty_result_keeps_requested_columns(http, key):
    http.get(f"{BASE}/api/flex/View", json=[])
    df = pdm.read_api_view("View", columns=["A", "B"])
    assert df.empty
    assert list(df.columns) == ["A", "B"]


def test_empty_result_without_columns(http, key):
    http.get(f"{BASE}/api/flex/View", json=[])
    assert pdm.read_api_view("View").empty


def test_out_of_range_date_does_not_fail_the_read(http, key):
    # 9999-12-31 ("no end date") is outside pandas 2.x's nanosecond range; it
    # must not fail the whole read. pandas 3 converts it, pandas 2 keeps it.
    http.get(
        f"{BASE}/api/flex/View",
        json=[
            {"PROD_DAY": "2024-01-01T00:00:00", "END_DATE": "9999-12-31T00:00:00"},
            {"PROD_DAY": "2024-01-02T00:00:00", "END_DATE": None},
        ],
    )

    df = pdm.read_api_view("View")

    assert pd.api.types.is_datetime64_any_dtype(df["PROD_DAY"])
    end = df["END_DATE"].iloc[0]
    if pd.api.types.is_datetime64_any_dtype(df["END_DATE"]):
        assert end == pd.Timestamp("9999-12-31")
    else:
        assert end == "9999-12-31T00:00:00"
    assert pd.isna(df["END_DATE"].iloc[1])


def test_impossible_date_leaves_column_unconverted(http, key):
    # Matches the ISO pattern but isn't a real date on any pandas version.
    http.get(
        f"{BASE}/api/flex/View",
        json=[
            {"PROD_DAY": "2024-01-01T00:00:00", "ODD": "2024-02-30T00:00:00"},
            {"PROD_DAY": "2024-01-02T00:00:00", "ODD": "2024-03-01T00:00:00"},
        ],
    )

    df = pdm.read_api_view("View")

    assert pd.api.types.is_datetime64_any_dtype(df["PROD_DAY"])
    assert not pd.api.types.is_datetime64_any_dtype(df["ODD"])
    assert list(df["ODD"]) == ["2024-02-30T00:00:00", "2024-03-01T00:00:00"]


@pytest.mark.parametrize(
    "error",
    [
        pd.errors.OutOfBoundsDatetime("out of bounds"),
        OverflowError("overflow"),
        ValueError("bad value"),
    ],
    ids=["out-of-bounds", "overflow", "value-error"],
)
def test_conversion_error_keeps_original_strings(monkeypatch, error):
    # Independent of the installed pandas version: whatever pandas raises for
    # an unconvertible column, the read keeps the original values.
    def failing_to_datetime(*args, **kwargs):
        raise error

    monkeypatch.setattr(api.pd, "to_datetime", failing_to_datetime)

    df = api._to_dataframe([{"D": "2024-01-01T00:00:00"}, {"D": None}])

    assert df["D"].iloc[0] == "2024-01-01T00:00:00"
    assert pd.isna(df["D"].iloc[1])


def test_unexpected_conversion_error_is_not_swallowed(monkeypatch):
    def failing_to_datetime(*args, **kwargs):
        raise TypeError("unexpected")

    monkeypatch.setattr(api.pd, "to_datetime", failing_to_datetime)

    with pytest.raises(TypeError):
        api._to_dataframe([{"D": "2024-01-01T00:00:00"}])


@pytest.mark.parametrize(
    "response",
    [
        {"json": {"not": "a list"}},
        {"body": "not json", "content_type": "text/plain"},
    ],
)
def test_unexpected_response_body_raises(http, key, response):
    http.get(f"{BASE}/api/flex/View", **response)
    with pytest.raises(PdmApiError):
        pdm.read_api_view("View")


def test_ping_returns_health_dict(http, key):
    http.get(f"{BASE}/api/Ping", json=PING_OK)
    assert pdm.ping() == PING_OK


def test_ping_rejects_non_object(http, key):
    http.get(f"{BASE}/api/Ping", json=[1, 2])
    with pytest.raises(PdmApiError):
        pdm.ping()


@pytest.mark.parametrize(
    "body, rows",
    [
        ([{"GOV_FIELD_NAME": "A"}, {"GOV_FIELD_NAME": "B"}], 2),
        ({"GOV_FIELD_NAME": "A"}, 1),
        ([], 0),
    ],
)
def test_user_access_returns_dataframe(http, key, body, rows):
    http.get(f"{BASE}/api/UserAccess", json=body)
    assert len(pdm.user_access()) == rows


# ---------------------------------------------------------------------------
# Environment and access token
# ---------------------------------------------------------------------------


def test_default_environment_is_prod():
    env = pdm.get_environment()
    assert env == api.ENVIRONMENTS["prod"]


def test_environment_from_env_var_and_setter(monkeypatch):
    monkeypatch.setenv(api.ENV_VAR_ENVIRONMENT, "TEST")
    assert pdm.get_environment().base_url == TEST_BASE

    pdm.set_environment("prod")
    assert pdm.get_environment().name == "prod"

    pdm.set_environment("")
    assert pdm.get_environment().name == "test"


def test_unknown_environment_raises(monkeypatch):
    with pytest.raises(ValueError):
        pdm.set_environment("staging")
    monkeypatch.setenv(api.ENV_VAR_ENVIRONMENT, "staging")
    with pytest.raises(ValueError):
        pdm.get_environment()


def test_base_url_and_client_id_overrides(monkeypatch, http, key, auth):
    monkeypatch.setenv(api.ENV_VAR_BASE_URL, "https://example.invalid/pdm/v3/")
    monkeypatch.setenv(api.ENV_VAR_CLIENT_ID, "client-override")
    http.get("https://example.invalid/pdm/v3/api/Ping", json=PING_OK)

    pdm.ping()

    assert http.calls[0].request.url.startswith("https://example.invalid/pdm/v3/api")
    assert auth.calls[0].client_id == "client-override"


def test_explicit_api_token_skips_sign_in(http, key, auth):
    pdm.set_api_token("explicit-token")
    http.get(f"{BASE}/api/Ping", json=PING_OK)

    pdm.ping()

    assert auth.calls == []
    assert http.calls[0].request.headers["Authorization"] == "Bearer explicit-token"


def test_api_token_uses_environment_scope(monkeypatch, auth):
    pdm.get_api_token()
    monkeypatch.setenv(api.ENV_VAR_ENVIRONMENT, "test")
    pdm.get_api_token()
    assert auth.scopes() == [
        api.ENVIRONMENTS["prod"].scope,
        api.ENVIRONMENTS["test"].scope,
    ]
    assert {c.tenant for c in auth.calls} == {api.TENANT_ID}


def test_account_selection_does_not_guess_from_windows_name(auth):
    pdm.get_api_token()  # nothing known yet: use the cached account
    pdm.get_api_token()  # remembered from the previous token's upn
    pdm.get_api_token(username="abcd")  # explicit short name
    pdm.get_api_token(username="x@statoil.com")  # explicit address kept
    assert [c.username for c in auth.calls] == [
        "",
        FAKE_UPN,
        "abcd@equinor.com",
        "x@statoil.com",
    ]


@pytest.mark.parametrize("token", ["not-a-jwt", "a.b.c", "a.bm90IGpzb24.c", ""])
def test_username_from_malformed_token_is_empty(token):
    assert api._username_from_token(token) == ""


# ---------------------------------------------------------------------------
# Subscription key (user-supplied only)
# ---------------------------------------------------------------------------


def test_missing_key_fails_before_sign_in_or_network(http, auth):
    with pytest.raises(SubscriptionKeyError) as err:
        pdm.ping()

    message = str(err.value)
    assert api.ENV_VAR_SUBSCRIPTION_KEY in message
    assert "set_subscription_key" in message
    assert "API portal" in message
    assert len(http.calls) == 0
    assert auth.calls == []


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_blank_env_var_counts_as_missing(monkeypatch, http, value):
    monkeypatch.setenv(api.ENV_VAR_SUBSCRIPTION_KEY, value)
    with pytest.raises(SubscriptionKeyError):
        pdm.ping()
    assert len(http.calls) == 0


def test_env_var_key_is_sent_stripped(monkeypatch, http):
    monkeypatch.setenv(api.ENV_VAR_SUBSCRIPTION_KEY, "  env-key \n")
    http.get(f"{BASE}/api/Ping", json=PING_OK)

    pdm.ping()

    assert http.calls[0].request.headers[api.SUBSCRIPTION_KEY_HEADER] == "env-key"


def test_set_subscription_key_wins_over_env_var(monkeypatch, http):
    monkeypatch.setenv(api.ENV_VAR_SUBSCRIPTION_KEY, "env-key")
    pdm.set_subscription_key("explicit-key")
    http.get(f"{BASE}/api/Ping", json=PING_OK)

    pdm.ping()

    assert http.calls[0].request.headers[api.SUBSCRIPTION_KEY_HEADER] == "explicit-key"


def test_clearing_set_subscription_key_falls_back_to_env_var(monkeypatch, http):
    monkeypatch.setenv(api.ENV_VAR_SUBSCRIPTION_KEY, "env-key")
    pdm.set_subscription_key("explicit-key")
    pdm.set_subscription_key("")
    http.get(f"{BASE}/api/Ping", json=PING_OK)

    pdm.ping()

    assert http.calls[0].request.headers[api.SUBSCRIPTION_KEY_HEADER] == "env-key"


def test_same_key_is_sent_for_the_test_environment(monkeypatch, http, key):
    monkeypatch.setenv(api.ENV_VAR_ENVIRONMENT, "test")
    http.get(f"{TEST_BASE}/api/Ping", json=PING_OK)

    pdm.ping()

    assert http.calls[0].request.url.startswith(TEST_BASE)
    assert http.calls[0].request.headers[api.SUBSCRIPTION_KEY_HEADER] == key


def test_rejected_key_is_not_retried(http, key, sleeps):
    http.get(f"{BASE}/api/Ping", **KEY_REJECTED)

    with pytest.raises(SubscriptionKeyError) as err:
        pdm.ping()

    assert len(http.calls) == 1
    assert sleeps == []
    assert api.ENV_VAR_SUBSCRIPTION_KEY in str(err.value)
    assert key not in str(err.value)


def test_no_key_vault_remnants():
    # Key Vault support was removed; make sure it doesn't come back unnoticed.
    for name in ("KEY_VAULT_URL", "ENV_VAR_KEY_VAULT_URL", "_get_key_from_vault"):
        assert not hasattr(api, name)
    assert "key_vault_secret" not in api.ApiEnvironment.__dataclass_fields__


# ---------------------------------------------------------------------------
# Retries and error handling
# ---------------------------------------------------------------------------


def test_429_is_retried_after_retry_after_seconds(http, key, sleeps):
    http.get(f"{BASE}/api/Ping", status=429, headers={"Retry-After": "2"})
    http.get(f"{BASE}/api/Ping", json=PING_OK)

    assert pdm.ping() == PING_OK
    assert sleeps == [2.0]


def test_retry_after_http_date_in_the_past_means_no_wait(http, key, sleeps):
    past = format_datetime(dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1))
    http.get(f"{BASE}/api/Ping", status=503, headers={"Retry-After": past})
    http.get(f"{BASE}/api/Ping", json=PING_OK)

    pdm.ping()
    assert sleeps == [0.0]


def test_retry_after_is_capped(http, key, sleeps):
    http.get(f"{BASE}/api/Ping", status=429, headers={"Retry-After": "3600"})
    http.get(f"{BASE}/api/Ping", json=PING_OK)

    pdm.ping()
    assert sleeps == [api._MAX_RETRY_DELAY_SECONDS]


@pytest.mark.parametrize("status", [429, 502, 503])
def test_retryable_status_gives_up_after_max_retries(http, key, sleeps, status):
    http.get(f"{BASE}/api/Ping", status=status, json={"message": "busy"})

    with pytest.raises(PdmApiError) as err:
        pdm.ping()

    assert err.value.status_code == status
    assert len(http.calls) == api._MAX_RETRIES + 1
    assert sleeps == [1.0, 2.0, 4.0]


def test_connection_error_is_retried(http, key, sleeps):
    http.get(f"{BASE}/api/Ping", body=requests.ConnectionError("down"))
    http.get(f"{BASE}/api/Ping", json=PING_OK)

    assert pdm.ping() == PING_OK
    assert sleeps == [1.0]


def test_connection_error_gives_up_after_max_retries(http, key, sleeps):
    http.get(f"{BASE}/api/Ping", body=requests.ConnectionError("down"))

    with pytest.raises(PdmApiError, match="Could not connect") as err:
        pdm.ping()
    # A plain connection failure is not a timeout.
    assert type(err.value) is PdmApiError
    assert len(http.calls) == api._MAX_RETRIES + 1


def test_connect_timeout_is_retried_then_succeeds(http, key, sleeps):
    http.get(f"{BASE}/api/Ping", body=requests.ConnectTimeout("connect timed out"))
    http.get(f"{BASE}/api/Ping", json=PING_OK)

    assert pdm.ping() == PING_OK
    assert len(http.calls) == 2
    assert sleeps == [1.0]


def test_connect_timeout_gives_up_with_timeout_error(http, key, sleeps):
    # ConnectTimeout is a ConnectionError, not a ReadTimeout, but callers
    # catching PdmTimeoutError must still see it as a timeout.
    http.get(f"{BASE}/api/Ping", body=requests.ConnectTimeout("connect timed out"))

    with pytest.raises(PdmTimeoutError) as err:
        pdm.ping()

    assert type(err.value) is PdmTimeoutError
    assert "Could not connect" in str(err.value)
    assert f"{api._CONNECT_TIMEOUT_SECONDS:g} s" in str(err.value)
    assert len(http.calls) == api._MAX_RETRIES + 1
    assert sleeps == [1.0, 2.0, 4.0]


def test_read_timeout_is_not_retried(http, key, sleeps):
    http.get(f"{BASE}/api/Ping", body=requests.ReadTimeout("slow"))

    with pytest.raises(PdmTimeoutError):
        pdm.ping(timeout=5)
    assert len(http.calls) == 1
    assert sleeps == []


# ---------------------------------------------------------------------------
# Redirects are never followed (credentials must stay on the gateway)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "location", [OTHER_HOST, f"{BASE}/api/Elsewhere"], ids=["other-host", "same-host"]
)
def test_redirect_is_not_followed(http, key, sleeps, status, location):
    http.get(f"{BASE}/api/Ping", status=status, headers={"Location": location})
    http.get(OTHER_HOST, json={})
    http.get(f"{BASE}/api/Elsewhere", json=PING_OK)

    with pytest.raises(PdmApiError) as err:
        pdm.ping()

    assert type(err.value) is PdmApiError
    assert err.value.status_code == status
    assert location in str(err.value)
    assert len(http.calls) == 1
    assert sleeps == []


def test_redirect_does_not_send_credentials_to_other_host(http, auth):
    pdm.set_subscription_key(SENTINEL_KEY)
    pdm.set_api_token(SENTINEL_TOKEN)
    http.get(f"{BASE}/api/flex/View", status=302, headers={"Location": OTHER_HOST})
    http.get(OTHER_HOST, json=[])

    with pytest.raises(PdmApiError) as err:
        pdm.read_api_view("View")

    assert all(not c.request.url.startswith(OTHER_HOST) for c in http.calls)
    for secret in (SENTINEL_KEY, SENTINEL_TOKEN):
        assert secret not in str(err.value)


def test_redirect_without_location_header(http, key):
    http.get(f"{BASE}/api/Ping", status=302)

    with pytest.raises(PdmApiError, match="unknown location") as err:
        pdm.ping()
    assert err.value.status_code == 302


@pytest.mark.parametrize(
    "response, error",
    [
        (KEY_REJECTED, SubscriptionKeyError),
        (TOKEN_REJECTED, PdmAuthError),
        ({"status": 403, "json": {"Error": "Forbidden"}}, PdmAuthError),
        ({"status": 408, "json": {}}, PdmTimeoutError),
        ({"status": 504, "body": "Gateway Timeout"}, PdmTimeoutError),
        (
            {"status": 404, "json": {"statusCode": 404, "message": "Not found"}},
            PdmApiError,
        ),
        ({"status": 500, "body": "<html>oops</html>"}, PdmApiError),
    ],
)
def test_error_responses_map_to_exceptions(http, key, sleeps, response, error):
    http.get(f"{BASE}/api/Ping", **response)

    with pytest.raises(error) as err:
        pdm.ping()

    assert type(err.value) is error
    assert err.value.status_code == response["status"]
    assert sleeps == []


@pytest.mark.parametrize(
    "body, message, trace_id",
    [
        (
            {
                "Error": "Invalid filter",
                "StatusCode": 400,
                "ErrorCode": 3,
                "TraceId": "t-1",
            },
            "Invalid filter",
            "t-1",
        ),
        (
            {"statusCode": 400, "message": "Bad request from APIM"},
            "Bad request from APIM",
            None,
        ),
    ],
)
def test_both_error_formats_are_parsed(http, key, body, message, trace_id):
    http.get(f"{BASE}/api/Ping", status=400, json=body)

    with pytest.raises(PdmApiError) as err:
        pdm.ping()

    assert message in str(err.value)
    assert err.value.trace_id == trace_id
    if trace_id:
        assert f"TraceId: {trace_id}" in str(err.value)


# ---------------------------------------------------------------------------
# Secrets never leak into errors or verbose output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        KEY_REJECTED,
        TOKEN_REJECTED,
        {"status": 500, "json": {"message": "boom"}},
        {"status": 302, "headers": {"Location": OTHER_HOST}},
        {"body": requests.ConnectionError("down")},
        {"body": requests.ConnectTimeout("connect timed out")},
        {"body": requests.ReadTimeout("slow")},
    ],
    ids=[
        "key-rejected",
        "token-rejected",
        "server-error",
        "redirect",
        "connection-error",
        "connect-timeout",
        "read-timeout",
    ],
)
def test_credentials_do_not_appear_in_errors_or_output(http, capsys, response):
    pdm.set_api_token(SENTINEL_TOKEN)
    pdm.set_subscription_key(SENTINEL_KEY)
    http.get(f"{BASE}/api/flex/View", status=429, headers={"Retry-After": "0"})
    http.get(f"{BASE}/api/flex/View", **response)

    with pytest.raises(PdmApiError) as err:
        pdm.read_api_view("View", filters={"A": "x"}, verbose=True)

    rendered = str(err.value) + repr(err.value.args) + capsys.readouterr().out
    assert "GET api/flex/View" in rendered  # verbose output was produced
    for secret in (SENTINEL_TOKEN, SENTINEL_KEY):
        assert secret not in rendered
        assert all(secret not in c.request.url for c in http.calls)
