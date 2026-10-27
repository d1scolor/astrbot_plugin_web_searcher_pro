import asyncio
import socket
from types import SimpleNamespace

import pytest
import pytest_asyncio
from astrbot_plugin_web_searcher_pro.errors import ExternalServiceError
from astrbot_plugin_web_searcher_pro.services.browser_http_client import BrowserHttpClient
from curl_cffi import CurlInfo, CurlOpt


@pytest_asyncio.fixture
async def transport(monkeypatch):
    calls, sessions, replies = [], [], []
    addresses = ["8.8.8.8"]

    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)

    class Session:
        def __init__(self, **kwargs):
            sessions.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, **kwargs):
            calls.append((url, kwargs))
            status, headers, chunks, peer = replies.pop(0)
            for chunk in chunks:
                if kwargs["content_callback"](chunk) != len(chunk):
                    raise RuntimeError("transfer aborted")
            return SimpleNamespace(status_code=status, headers=headers, infos={CurlInfo.PRIMARY_IP: peer})

    monkeypatch.setattr("curl_cffi.requests.AsyncSession", Session)
    return calls, sessions, replies, addresses


@pytest.mark.asyncio
async def test_browser_fetch_pins_dns_and_disables_proxy(monkeypatch, transport):
    calls, sessions, replies, _ = transport
    monkeypatch.setenv("ALL_PROXY", "http://synthetic.invalid:8888")
    replies.append((200, {}, [b"hello"], "8.8.8.8"))
    status, text, _ = await BrowserHttpClient().get_text("https://example.com/page")
    assert (status, text) == (200, "hello")
    options = sessions[0]["curl_options"]
    assert options[CurlOpt.RESOLVE] == [b"example.com:443:8.8.8.8"]
    assert options[CurlOpt.PROXY] == b"" and options[CurlOpt.FOLLOWLOCATION] == 0
    assert options[CurlOpt.PROTOCOLS] == 3 and sessions[0]["trust_env"] is False
    assert calls[0][1]["verify"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.1.2.3/",
        "http://localhost/",
        "https://example.com:8443/",
        "file:///etc/passwd",
    ],
)
async def test_private_or_unsupported_url_never_connects(url, transport):
    calls, _, _, _ = transport
    with pytest.raises(ExternalServiceError):
        await BrowserHttpClient().get_text(url)
    assert not calls


@pytest.mark.asyncio
async def test_mixed_dns_answers_never_connect(transport):
    calls, _, _, addresses = transport
    addresses.append("127.0.0.1")
    with pytest.raises(ExternalServiceError):
        await BrowserHttpClient().get_text("https://example.com/")
    assert not calls


@pytest.mark.asyncio
async def test_private_redirect_is_rejected(transport):
    calls, _, replies, _ = transport
    replies.append((302, {"Location": "http://127.0.0.1/secret"}, [], "8.8.8.8"))
    with pytest.raises(ExternalServiceError):
        await BrowserHttpClient().get_text("https://example.com/")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_public_redirect_revalidates_and_recreates_session(transport):
    calls, sessions, replies, _ = transport
    replies.extend(
        [(302, {"Location": "https://other.example/page"}, [], "8.8.8.8"), (200, {}, [b"article"], "8.8.8.8")]
    )
    assert (await BrowserHttpClient().get_text("https://example.com/"))[1] == "article"
    assert len(sessions) == 2 and len(calls) == 2
    assert sessions[1]["curl_options"][CurlOpt.RESOLVE] == [b"other.example:443:8.8.8.8"]


@pytest.mark.asyncio
async def test_decoded_body_limit_aborts_without_large_buffer(transport):
    _, _, replies, _ = transport
    replies.append((200, {}, [b"12345", b"67890"], "8.8.8.8"))
    with pytest.raises(ExternalServiceError, match="download limit"):
        await BrowserHttpClient(max_bytes=8).get_text("https://example.com/")


@pytest.mark.asyncio
async def test_peer_must_match_validated_address(transport):
    _, _, replies, _ = transport
    replies.append((200, {}, [b"content"], "1.1.1.1"))
    with pytest.raises(ExternalServiceError, match="validated DNS"):
        await BrowserHttpClient().get_text("https://example.com/")
