import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from astrbot_plugin_web_searcher_pro.config import PluginConfig
from astrbot_plugin_web_searcher_pro.errors import ExternalServiceError
from astrbot_plugin_web_searcher_pro.search_models import SearchResult
from astrbot_plugin_web_searcher_pro.services.prompt_guard import PromptGuard
from astrbot_plugin_web_searcher_pro.services.search_budget import SearchBudget
from astrbot_plugin_web_searcher_pro.services.searxng_service import SearxngService


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 500, 502, 503])
async def test_http_failure_is_not_an_empty_search(status):
    http = SimpleNamespace(get_json=AsyncMock(return_value=(status, {})))
    result = await SearxngService(http, "https://search.example").search("test")
    assert result.error_code == "http_error"
    assert result.diagnostics["http_status"] == status
    assert "No information" not in result.error_message


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"results": None}, {"results": "invalid"}, []])
async def test_missing_or_invalid_results_are_diagnostic_errors(payload):
    http = SimpleNamespace(get_json=AsyncMock(return_value=(200, payload)))
    result = await SearxngService(http, "https://search.example").search("test")
    assert result.error_code == "invalid_response"


@pytest.mark.asyncio
async def test_network_exception_text_cannot_leak():
    http = SimpleNamespace(get_json=AsyncMock(side_effect=ExternalServiceError("synthetic-private-token")))
    result = await SearxngService(http, "https://search.example").search("test")
    assert result.error_code == "backend_request_failed"
    assert "synthetic-private-token" not in str(result)


@pytest.mark.asyncio
async def test_empty_with_engine_failures_is_inconclusive():
    http = SimpleNamespace(
        get_json=AsyncMock(
            return_value=(
                200,
                {"results": [], "unresponsive_engines": [["engine", "private diagnostic must not leak"]]},
            )
        )
    )
    result = await SearxngService(http, "https://search.example").search("test")
    assert result.error_code == "engine_failures"
    assert result.diagnostics["engine_failure_count"] == 1
    assert "private diagnostic" not in str(result)


@pytest.mark.asyncio
async def test_malformed_score_and_entry_do_not_erase_valid_results():
    http = SimpleNamespace(
        get_json=AsyncMock(
            return_value=(
                200,
                {
                    "results": [None, {"title": "Useful", "url": "https://example.org", "score": "NaN"}],
                    "unresponsive_engines": [["other", "timeout"]],
                },
            )
        )
    )
    result = await SearxngService(http, "https://search.example").search("test")
    assert result.results[0].title == "Useful" and result.results[0].score == 0
    assert result.diagnostics["invalid_result_count"] == 1
    assert result.diagnostics["raw_result_count"] == 2
    assert result.diagnostics["engine_failure_count"] == 1


def test_budget_is_shared_by_category_and_new_event_is_fresh():
    event = SimpleNamespace()
    budget = SearchBudget.for_event(event)
    for i in range(6):
        assert budget.claim("images" if i % 2 else "general", f"query{i}") == ""
    assert SearchBudget.for_event(event).claim("news", "new query") == "search_budget_exhausted"
    assert SearchBudget.for_event(SimpleNamespace()).claim("general", "query0") == ""


def test_duplicate_and_failure_cutoffs():
    budget = SearchBudget()
    assert budget.claim("general", "A  Query") == ""
    assert budget.claim("general", "a query") == "duplicate_search"
    budget.record(SearchResult(error_code="http_error", error_message="failure"))
    budget.record(SearchResult(error_code="http_error", error_message="failure"))
    assert budget.claim("images", "different") == "repeated_backend_failure"
    budget = SearchBudget()
    for i in range(3):
        assert budget.claim("general", str(i)) == ""
        budget.record(SearchResult())
    assert budget.claim("general", "fourth") == "repeated_empty_results"


@pytest.mark.asyncio
async def test_model_retries_do_not_repeat_network_calls(monkeypatch):
    import json

    from test_package_import import _import_plugin_main

    module = _import_plugin_main(monkeypatch)
    plugin = object.__new__(module.WebSearcherPro)
    plugin.plugin_config = PluginConfig()
    plugin.guard = PromptGuard()
    plugin.searxng_service = SimpleNamespace(search=AsyncMock(return_value=SearchResult()))
    event = SimpleNamespace()
    for i in range(10):
        result = json.loads(await plugin.search_general(event, f"query {i}"))
    assert plugin.searxng_service.search.await_count == 3
    assert result["search_status"] == "repeated_empty_results"
    assert result["stop_searching"] is True
    assert result["trusted"] is False


@pytest.mark.asyncio
async def test_parallel_calls_share_hard_total_budget(monkeypatch):
    from test_package_import import _import_plugin_main

    module = _import_plugin_main(monkeypatch)
    plugin = object.__new__(module.WebSearcherPro)
    plugin.plugin_config = PluginConfig(search_call_limit=2)
    plugin.guard = PromptGuard()

    async def search(*args, **kwargs):
        await asyncio.sleep(0)
        return SearchResult()

    plugin.searxng_service = SimpleNamespace(search=AsyncMock(side_effect=search))
    event = SimpleNamespace()
    await asyncio.gather(*(plugin.search_general(event, f"query {i}") for i in range(8)))
    assert plugin.searxng_service.search.await_count == 2


@pytest.mark.asyncio
async def test_engine_error_reasons_are_whitelisted_counts():
    http = SimpleNamespace(
        get_json=AsyncMock(
            return_value=(
                200,
                {
                    "results": [],
                    "unresponsive_engines": [
                        ["a", "CAPTCHA"],
                        ["b", "HTTP 429"],
                        ["c", "timeout"],
                        ["d", "synthetic-secret"],
                    ],
                },
            )
        )
    )
    result = await SearxngService(http, "https://search.example").search("test")
    assert result.diagnostics["engine_failure_reasons"] == {
        "captcha": 1,
        "rate_limited": 1,
        "timeout": 1,
        "other": 1,
    }
    assert "synthetic-secret" not in str(result.diagnostics)
