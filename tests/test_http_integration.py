import json

from aiohttp import web
from aiohttp.test_utils import TestServer
from astrbot_plugin_web_searcher_pro.services.http_client import HttpClient
from astrbot_plugin_web_searcher_pro.services.prompt_guard import PromptGuard


async def test_real_http_guard_auth_and_roundtrip():
    seen = []

    async def scan(request):
        assert request.headers["Authorization"] == "Bearer synthetic-token"
        payload = await request.json()
        item = payload["inputs"][0]
        seen.append(item["text"])
        malicious = "test-block" in item["text"]
        return web.json_response(
            {
                "results": [
                    {
                        "id": item["id"],
                        "classification": "malicious" if malicious else "benign",
                        "score": 0.99 if malicious else 0.01,
                        "chunks_scanned": 1,
                    }
                ],
                "detector": {"threshold": 0.9},
            }
        )

    app = web.Application()
    app.router.add_post("/v1/scan", scan)
    async with TestServer(app) as server:
        guard = PromptGuard(
            enabled=True, base_url=str(server.make_url("/")).rstrip("/"), token="synthetic-token"
        )
        good = json.loads(await guard.review("A character reference"))
        bad = json.loads(await guard.review("test-block"))
        assert good["screening"] == "accepted"
        assert bad["screening"] == "blocked" and "text" not in bad
        assert len(seen) == 2


async def test_real_trusted_search_endpoint_and_redirect_rejection():
    async def search(request):
        if request.query.get("q") == "redirect":
            raise web.HTTPFound("/admin")
        return web.json_response({"results": []})

    app = web.Application()
    app.router.add_get("/search", search)
    async with TestServer(app) as server:
        client = HttpClient(trusted_base=str(server.make_url("/")).rstrip("/"))
        status, result = await client.get_json(str(server.make_url("/search")), params={"q": "hello"})
        assert status == 200 and result["results"] == []
        import pytest
        from astrbot_plugin_web_searcher_pro.errors import ExternalServiceError

        with pytest.raises(ExternalServiceError):
            await client.get_json(str(server.make_url("/search")), params={"q": "redirect"})


async def test_diagnostics_checks_health_readiness_and_real_scan():
    seen = []

    async def health(request):
        assert "Authorization" not in request.headers
        seen.append("health")
        return web.json_response({"status": "ok"})

    async def ready(request):
        assert request.headers.get("Authorization") == "Bearer synthetic-token"
        seen.append("readiness")
        return web.json_response({"status": "ready"})

    async def scan(request):
        from astrbot_plugin_web_searcher_pro.services.prompt_guard import PROBE_TEXT

        payload = await request.json()
        assert payload["inputs"][0]["text"] == PROBE_TEXT
        assert request.headers.get("Authorization") == "Bearer synthetic-token"
        seen.append("scan")
        return web.json_response(
            {
                "results": [
                    {
                        "id": payload["inputs"][0]["id"],
                        "classification": "benign",
                        "score": 0.01,
                        "chunks_scanned": 1,
                    }
                ],
                "detector": {"threshold": 0.9},
            }
        )

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/ready", ready)
    app.router.add_post("/v1/scan", scan)
    async with TestServer(app) as server:
        # Diagnostics should work even when screening is currently disabled.
        guard = PromptGuard(base_url=str(server.make_url("/")).rstrip("/"), token="synthetic-token")
        result = await guard.diagnostics()
        assert result["ok"] is True and result["enabled"] is False
        assert seen == ["health", "readiness", "scan"]
        assert "synthetic-token" not in json.dumps(result)
        assert str(server.make_url("/")) not in json.dumps(result)


async def test_diagnostics_identifies_bad_token_without_echoing_server_body():
    async def health(request):
        return web.json_response({"status": "ok"})

    async def ready(request):
        return web.Response(status=401, text="sensitive-server-body synthetic-token")

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/ready", ready)
    async with TestServer(app) as server:
        result = await PromptGuard(
            base_url=str(server.make_url("/")).rstrip("/"), token="synthetic-token"
        ).diagnostics()
        assert result["ok"] is False
        assert result["code"] == "authentication_failed"
        assert result["checks"][-1] == {"stage": "readiness", "ok": False, "http_status": 401}
        assert "synthetic-token" not in json.dumps(result)
        assert "sensitive-server-body" not in json.dumps(result)


async def test_diagnostics_distinguishes_invalid_scan_response():
    async def healthy(request):
        return web.json_response({"status": "ok"})

    async def broken(request):
        return web.json_response({"unexpected": "sensitive-server-body"})

    app = web.Application()
    app.router.add_get("/health", healthy)
    app.router.add_get("/ready", healthy)
    app.router.add_post("/v1/scan", broken)
    async with TestServer(app) as server:
        result = await PromptGuard(base_url=str(server.make_url("/")).rstrip("/")).diagnostics()
        assert result["code"] == "invalid_response" and result["checks"][-1]["stage"] == "scan"
        assert "sensitive-server-body" not in json.dumps(result)
