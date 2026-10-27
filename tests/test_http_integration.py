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
