import asyncio
import json
import socket

import pytest
from astrbot_plugin_web_searcher_pro.errors import ExternalServiceError
from astrbot_plugin_web_searcher_pro.services.http_client import HttpClient
from astrbot_plugin_web_searcher_pro.services.network_policy import PublicResolver, validate_public_url
from astrbot_plugin_web_searcher_pro.services.prompt_guard import PromptGuard


@pytest.mark.parametrize(
    "url",
    [
        "http://2130706433/",
        "http://127.1/",
        "http://0177.0.0.1/",
        "http://①②⑦.⓪.⓪.①/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[64:ff9b::a00:1]/",
        "http://224.0.0.1/",
        "http://localhost/",
        "http://localhost./",
        "http://foo.local/",
        "file:///etc/passwd",
        "http://user:pass@example.org/",
        "https://example.org:8000/",
    ],
)
def test_private_urls_blocked(url):
    with pytest.raises(ExternalServiceError):
        validate_public_url(url)


async def test_dns_rebinding_blocked_at_connection(monkeypatch):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(ExternalServiceError):
        await PublicResolver().resolve("public.example", 80)


def test_infrastructure_exception_is_scoped():
    client = HttpClient(trusted_base="http://10.0.0.1:8888")
    client.validate("http://10.0.0.1:8888/search")
    for url in ("http://10.0.0.2:8888/search", "http://10.0.0.1:8888/admin", "http://127.0.0.1/search"):
        with pytest.raises(ExternalServiceError):
            client.validate(url)
    with pytest.raises(ExternalServiceError):
        HttpClient(proxy="http://proxy.example")


async def test_guard_optional_and_fail_closed():
    assert json.loads(await PromptGuard().review("external")) == {
        "screening": "disabled",
        "trusted": False,
        "text": "external",
    }
    result = json.loads(await PromptGuard(enabled=True).review("external"))
    assert result["screening"] == "unavailable" and "text" not in result


@pytest.mark.parametrize("failure", [TimeoutError(), ValueError("bad"), RuntimeError("offline")])
async def test_guard_errors_do_not_return_external_text(failure):
    guard = PromptGuard(enabled=True, base_url="http://guard.example")

    async def scan(text):
        raise failure

    guard.scan = scan
    result = json.loads(await guard.review("UNTRUSTED_MARKER"))
    assert result["screening"] == "unavailable"
    assert "UNTRUSTED_MARKER" not in json.dumps(result)


async def test_guard_blocks_or_accepts_without_echoing_blocked_text():
    guard = PromptGuard(enabled=True, base_url="http://guard.example")

    async def malicious(text):
        return True

    guard.scan = malicious
    result = json.loads(await guard.review("UNTRUSTED_MARKER"))
    assert result["screening"] == "blocked" and "text" not in result

    async def benign(text):
        return False

    guard.scan = benign
    result = json.loads(await guard.review("ordinary fact"))
    assert result["screening"] == "accepted" and result["trusted"] is False


class Response:
    def __init__(self, body=b"", status=200, headers=None, url="https://example.org/"):
        self.status, self.headers, self.url = status, headers or {}, url
        self.content = self
        self.body = body

    async def iter_chunked(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start : start + size]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def request(self, method, url, **kwargs):
        self.calls.append(url)
        return self.responses.pop(0)


async def test_public_redirect_cannot_reach_private_host(monkeypatch):
    from astrbot_plugin_web_searcher_pro.services import http_client

    session = Session([Response(status=302, headers={"Location": "http://127.0.0.1/"})])
    monkeypatch.setattr(http_client.aiohttp, "ClientSession", lambda **kwargs: session)
    # Fake the connector too; no real sockets are opened by this test.
    monkeypatch.setattr(http_client.aiohttp, "TCPConnector", lambda **kwargs: None)
    with pytest.raises(ExternalServiceError):
        await HttpClient().get_text("https://example.org/")
    assert session.calls == ["https://example.org/"]


async def test_body_limit_enforced(monkeypatch):
    from astrbot_plugin_web_searcher_pro.services import http_client

    session = Session([Response(b"x" * 100)])
    monkeypatch.setattr(http_client.aiohttp, "ClientSession", lambda **kwargs: session)
    monkeypatch.setattr(http_client.aiohttp, "TCPConnector", lambda **kwargs: None)
    with pytest.raises(ExternalServiceError):
        await HttpClient(max_bytes=32).get_text("https://example.org/")


class GuardSession:
    def __init__(self, mutate=lambda value: value, status=200):
        self.mutate, self.status, self.calls = mutate, status, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def post(self, url, **kwargs):
        request = kwargs["json"]
        self.calls.append((url, kwargs))
        payload = {
            "results": [
                {
                    "id": request["inputs"][0]["id"],
                    "classification": "benign",
                    "score": 0.1,
                    "chunks_scanned": 2,
                }
            ],
            "detector": {"threshold": 0.9},
        }
        return Response(json.dumps(self.mutate(payload)).encode(), status=self.status)


async def test_guard_api_contract_and_auth(monkeypatch):
    from astrbot_plugin_web_searcher_pro.services import prompt_guard

    session = GuardSession()
    monkeypatch.setattr(prompt_guard.aiohttp, "ClientSession", lambda **kwargs: session)
    guard = PromptGuard(enabled=True, base_url="http://10.0.0.1:8005", token="synthetic-token")
    result = json.loads(await guard.review("External content"))
    assert result["screening"] == "accepted"
    url, options = session.calls[0]
    assert url == "http://10.0.0.1:8005/v1/scan"
    assert options["headers"] == {"Authorization": "Bearer synthetic-token"}
    assert options["allow_redirects"] is False
    assert options["json"]["options"]["include_excerpts"] is False
    assert options["json"]["inputs"][0]["text"] == "External content"
    assert "synthetic-token" not in json.dumps(result)


@pytest.mark.parametrize(
    "case", ["missing", "duplicate", "wrong_id", "unknown", "nan", "empty_chunks", "bad_threshold"]
)
async def test_malformed_guard_results_fail_closed(monkeypatch, case):
    from astrbot_plugin_web_searcher_pro.services import prompt_guard

    def mutate(payload):
        row = payload["results"][0]
        if case == "missing":
            payload["results"] = []
        elif case == "duplicate":
            payload["results"].append(dict(row))
        elif case == "wrong_id":
            row["id"] = "unrelated"
        elif case == "unknown":
            row["classification"] = "unknown"
        elif case == "nan":
            row["score"] = float("nan")
        elif case == "empty_chunks":
            row["chunks_scanned"] = 0
        elif case == "bad_threshold":
            payload["detector"]["threshold"] = "0.9"
        return payload

    session = GuardSession(mutate)
    monkeypatch.setattr(prompt_guard.aiohttp, "ClientSession", lambda **kwargs: session)
    result = json.loads(
        await PromptGuard(enabled=True, base_url="http://guard.example").review("UNTRUSTED_MARKER")
    )
    assert result["screening"] == "unavailable" and "text" not in result


@pytest.mark.parametrize("status", [301, 401, 429, 503, 504])
async def test_guard_http_errors_fail_closed(monkeypatch, status):
    from astrbot_plugin_web_searcher_pro.services import prompt_guard

    monkeypatch.setattr(prompt_guard.aiohttp, "ClientSession", lambda **kwargs: GuardSession(status=status))
    result = json.loads(
        await PromptGuard(enabled=True, base_url="http://guard.example").review("UNTRUSTED_MARKER")
    )
    assert result["screening"] == "unavailable" and "text" not in result


async def test_guard_never_sends_oversized_text(monkeypatch):
    from astrbot_plugin_web_searcher_pro.services.prompt_guard import MAX_TEXT_BYTES

    guard = PromptGuard(enabled=True, base_url="http://guard.example")

    async def forbidden(text):
        raise AssertionError("Oversized content must not be sent")

    monkeypatch.setattr(guard, "scan", forbidden)
    result = json.loads(await guard.review("x" * (MAX_TEXT_BYTES + 1)))
    assert result["screening"] == "unavailable"


async def test_diagnostics_missing_configuration_and_busy():
    result = await PromptGuard().diagnostics()
    assert result["code"] == "configuration_missing"
    guard = PromptGuard(base_url="http://guard.example")
    async with guard.diagnostic_lock:
        result = await guard.diagnostics()
    assert result["code"] == "busy"


async def test_diagnostics_reports_timeout(monkeypatch):
    from astrbot_plugin_web_searcher_pro.services import prompt_guard

    class SlowSession(Session):
        def get(self, *args, **kwargs):
            raise TimeoutError()

    monkeypatch.setattr(prompt_guard.aiohttp, "ClientSession", lambda **kwargs: SlowSession([]))
    result = await PromptGuard(base_url="http://guard.example").diagnostics()
    assert result["code"] == "timeout"
    assert result["checks"][-1]["stage"] == "health"
