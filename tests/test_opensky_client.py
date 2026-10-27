import pytest
import requests

from fda.config import ACY_BBOX
from fda.opensky import (
    STATES_URL,
    TOKEN_URL,
    OpenSkyClient,
    RateLimited,
    SchemaError,
    UpstreamError,
)
from tests.conftest import FakeResponse, FakeSession

OK_BODY = {"time": 1793144103, "states": []}


def client(session, **kw):
    sleeps: list[float] = []
    c = OpenSkyClient(session=session, sleep=sleeps.append, **kw)
    return c, sleeps


def test_request_uses_bbox_and_extended(sample_body):
    s = FakeSession(gets=[FakeResponse(200, sample_body, {"X-Rate-Limit-Remaining": "399"})])
    c, _ = client(s)
    resp = c.fetch_states(ACY_BBOX)

    call = s.get_calls[0]
    assert call["url"] == STATES_URL
    assert call["params"] == {**ACY_BBOX.as_params(), "extended": 1}
    assert call["timeout"] > 0
    assert resp.api_time == sample_body["time"]
    assert len(resp.rows) == 33
    assert resp.credits_remaining == 399


def test_anonymous_sends_no_auth_header():
    s = FakeSession(gets=[FakeResponse(200, OK_BODY)])
    c, _ = client(s)
    c.fetch_states(ACY_BBOX)
    assert "Authorization" not in s.get_calls[0]["headers"]
    assert s.post_calls == []


def test_oauth_token_fetched_once_and_reused():
    s = FakeSession(
        gets=[FakeResponse(200, OK_BODY), FakeResponse(200, OK_BODY)],
        posts=[FakeResponse(200, {"access_token": "tok123", "expires_in": 1800})],
    )
    c, _ = client(s, client_id="id", client_secret="secret")
    c.fetch_states(ACY_BBOX)
    c.fetch_states(ACY_BBOX)

    assert len(s.post_calls) == 1
    assert s.post_calls[0]["url"] == TOKEN_URL
    assert s.post_calls[0]["data"]["grant_type"] == "client_credentials"
    assert all(g["headers"]["Authorization"] == "Bearer tok123" for g in s.get_calls)


def test_token_failure_is_upstream_error():
    s = FakeSession(posts=[FakeResponse(401, {})])
    c, _ = client(s, client_id="id", client_secret="bad")
    with pytest.raises(UpstreamError):
        c.fetch_states(ACY_BBOX)


def test_429_raises_rate_limited_without_retry():
    s = FakeSession(gets=[FakeResponse(429, None, {"X-Rate-Limit-Retry-After-Seconds": "3600"})])
    c, sleeps = client(s)
    with pytest.raises(RateLimited) as exc:
        c.fetch_states(ACY_BBOX)
    assert exc.value.retry_after_s == 3600
    assert len(s.get_calls) == 1
    assert sleeps == []


def test_5xx_retried_with_backoff_then_succeeds():
    s = FakeSession(gets=[FakeResponse(503), FakeResponse(502), FakeResponse(200, OK_BODY)])
    c, sleeps = client(s, backoff_s=2.0)
    assert c.fetch_states(ACY_BBOX).api_time == OK_BODY["time"]
    assert sleeps == [2.0, 4.0]


def test_5xx_gives_up_after_max_retries():
    s = FakeSession(gets=[FakeResponse(500)] * 3)
    c, sleeps = client(s, max_retries=2)
    with pytest.raises(UpstreamError) as exc:
        c.fetch_states(ACY_BBOX)
    assert exc.value.http_status == 500
    assert len(s.get_calls) == 3
    assert len(sleeps) == 2


def test_network_error_retried_then_raised():
    s = FakeSession(gets=[requests.ConnectionError("dns")] * 3)
    c, _ = client(s)
    with pytest.raises(UpstreamError, match="network error"):
        c.fetch_states(ACY_BBOX)
    assert len(s.get_calls) == 3


def test_4xx_not_retried():
    s = FakeSession(gets=[FakeResponse(400)])
    c, _ = client(s)
    with pytest.raises(UpstreamError):
        c.fetch_states(ACY_BBOX)
    assert len(s.get_calls) == 1


def test_null_states_means_empty_sky():
    s = FakeSession(gets=[FakeResponse(200, {"time": 1, "states": None})])
    c, _ = client(s)
    assert c.fetch_states(ACY_BBOX).rows == []


@pytest.mark.parametrize(
    "resp",
    [
        FakeResponse(200, text="<html>maintenance</html>"),
        FakeResponse(200, ["not", "a", "dict"]),
        FakeResponse(200, {"states": []}),
        FakeResponse(200, {"time": 1, "states": "oops"}),
    ],
)
def test_malformed_body_raises_schema_error(resp):
    c, _ = client(FakeSession(gets=[resp]))
    with pytest.raises(SchemaError):
        c.fetch_states(ACY_BBOX)
