import pytest
from astrbot_plugin_web_searcher_pro.services.web_fetch_service import WebFetchService


class DummyHttpClient:
    def __init__(self, html: str, status: int = 200):
        self.html = html
        self.status = status

    async def get_text(self, url: str, *, params=None, headers=None):
        return self.status, self.html, {}


class DummyGitHubService:
    async def search(self, query: str) -> str:
        return f"github:{query}"


@pytest.mark.asyncio
async def test_fetch_returns_plain_text_for_readable_pages():
    html = """
    <html>
      <head><title>Example Article</title></head>
      <body>
        <article>
          <h1>Example Article</h1>
          <p>This is a readable article body with enough text to make readability extraction useful.</p>
          <p>It should be returned as plain text instead of raw HTML so downstream tools get meaningful content.</p>
        </article>
      </body>
    </html>
    """
    service = WebFetchService(DummyHttpClient(html), DummyGitHubService())

    result = await service.fetch("https://example.com/article")

    assert "Example Article" in result
    assert "meaningful content" in result
    assert "<article>" not in result


@pytest.mark.asyncio
async def test_fetch_falls_back_to_metadata_for_client_rendered_pages():
    html = """
    <!doctype html>
    <html lang="zh-CN">
      <head>
        <meta charset="UTF-8" />
        <title>AstrBot - Agentic AI 助手</title>
      </head>
      <body>
        <div id="root"></div>
      </body>
    </html>
    """
    service = WebFetchService(DummyHttpClient(html), DummyGitHubService())

    result = await service.fetch("https://astrbot.app/")

    assert "AstrBot - Agentic AI 助手" in result
    assert "client-rendered" in result


@pytest.mark.asyncio
async def test_blocked_page_uses_browser_fallback():
    from unittest.mock import AsyncMock

    browser = AsyncMock()
    browser.get_text.return_value = (
        200,
        "<article><p>" + "Readable article content. " * 12 + "</p></article>",
        {},
    )
    service = WebFetchService(DummyHttpClient("blocked", 403), DummyGitHubService(), browser)
    result = await service.fetch("https://example.com/page")
    assert "Readable article content" in result
    browser.get_text.assert_awaited_once_with("https://example.com/page")


@pytest.mark.asyncio
async def test_success_and_rate_limit_do_not_retry_browser():
    from unittest.mock import AsyncMock

    browser = AsyncMock()
    for status in (200, 429):
        service = WebFetchService(
            DummyHttpClient("<p>" + "Article text. " * 20 + "</p>", status), DummyGitHubService(), browser
        )
        result = await service.fetch("https://example.com/page")
        if status == 429:
            assert "429" in result
    browser.get_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_challenge_is_not_presented_as_article():
    from unittest.mock import AsyncMock

    browser = AsyncMock()
    challenge = "<title>Just a moment...</title><div>Verify you are human</div>"
    browser.get_text.return_value = (200, challenge, {})
    service = WebFetchService(DummyHttpClient(challenge), DummyGitHubService(), browser)
    result = await service.fetch("https://example.com/page")
    assert "anti-bot challenge" in result
    browser.get_text.assert_awaited_once()
