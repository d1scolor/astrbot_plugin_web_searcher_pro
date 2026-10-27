import asyncio
from collections.abc import Mapping
from dataclasses import replace
from typing import Iterable

from ..errors import ExternalServiceError
from ..search_models import SearchResult, SearchResultItem
from ..utils.query_language import detect_query_language
from .http_client import HttpClient
from .image_service import rank_image_results
from .network_policy import validate_public_url
from .result_ranking import rank_text_results
from .search_strategy import get_search_strategy


def deduplicate_results(items: Iterable[SearchResultItem]) -> list[SearchResultItem]:
    best_by_url: dict[str, SearchResultItem] = {}
    order_by_url: list[str] = []
    for item in items:
        key = item.url.strip()
        if not key:
            key = f"__untitled__:{len(order_by_url)}"
        existing = best_by_url.get(key)
        if existing is None:
            best_by_url[key] = item
            order_by_url.append(key)
            continue
        if item.score > existing.score:
            best_by_url[key] = item
    return [best_by_url[key] for key in order_by_url]


def filter_results(
    result: SearchResult,
    category: str,
    limit: int,
    engines: list[str] | None = None,
    *,
    ranking_profile: str = "default",
) -> SearchResult:
    if result.error_message:
        return result
    items = list(result.results)
    if engines:
        items = [item for item in items if item.engine in engines]
    items = deduplicate_results(items)
    if category != "images":
        items = rank_text_results(items, profile=ranking_profile)
        return replace(result, results=items[:limit])
    return replace(result, results=items[:limit])


class SearxngService:
    def __init__(
        self,
        http_client: HttpClient,
        base_url: str,
        *,
        image_candidate_limit: int = 10,
        image_result_limit: int = 5,
    ):
        self.http_client = http_client
        self.base_url = base_url.rstrip("/")
        self.image_candidate_limit = max(1, min(image_candidate_limit, 20))
        self.image_result_limit = max(1, min(image_result_limit, 10))

    async def search(self, query: str, *, category="general", limit=5, engines=None):
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            return SearchResult(
                error_message="Search query must contain 1–2000 characters.", error_code="invalid_query"
            )
        try:
            async with asyncio.timeout(getattr(self.http_client, "timeout", 15)):
                return await self._search(
                    query, category=category, limit=max(1, min(limit, 10)), engines=engines
                )
        except TimeoutError:
            return SearchResult(
                error_message="Search deadline exceeded; no conclusion about matching pages can be drawn.",
                error_code="timeout",
            )

    async def _search(
        self, query: str, *, category: str = "general", limit: int = 5, engines: list[str] | None = None
    ) -> SearchResult:
        if category != "images":
            return await self._search_text(query, category=category, limit=limit, engines=engines)

        result = await self._request_search(
            query,
            category=category,
            limit=max(limit, self.image_candidate_limit),
            lang="zh",
        )
        if result.error_message:
            return result
        if result.is_empty:
            return result
        return await self._filter_image_results(result, engines=engines, limit=limit)

    async def _request_search(self, query: str, *, category: str, limit: int, lang: str) -> SearchResult:
        params = {
            "q": query,
            "categories": category,
            "format": "json",
            "lang": lang,
            "limit": limit,
        }
        try:
            status, data = await self.http_client.get_json(f"{self.base_url}/search", params=params)
        except ExternalServiceError:
            return SearchResult(
                error_message="Search backend request failed or was blocked. This is not an empty search result.",
                error_code="backend_request_failed",
            )
        except (TypeError, ValueError):
            return SearchResult(
                error_message="Search backend returned invalid JSON. Check its JSON search interface.",
                error_code="invalid_json",
            )
        diagnostics = {"http_status": status}
        if status == 403:
            return SearchResult(
                error_message="SearXNG returned 403 Forbidden. Please check whether the /search JSON interface is enabled and reachable.",
                error_code="http_error",
                diagnostics=diagnostics,
            )
        if status != 200:
            return SearchResult(
                error_message=f"Search backend returned HTTP {status}; this is not evidence that no pages match.",
                error_code="http_error",
                diagnostics=diagnostics,
            )
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            return SearchResult(
                error_message="Search backend response has no valid results list.",
                error_code="invalid_response",
                diagnostics=diagnostics,
            )
        raw_results = data["results"]
        failures = data.get("unresponsive_engines", [])
        diagnostics.update(
            raw_result_count=len(raw_results),
            engine_failure_count=len(failures) if isinstance(failures, list) else 0,
            invalid_result_count=sum(not isinstance(item, Mapping) for item in raw_results),
        )
        reasons = {}
        for item in failures if isinstance(failures, list) else []:
            detail = str(item[1]).casefold() if isinstance(item, (list, tuple)) and len(item) > 1 else ""
            reason = (
                "captcha"
                if "captcha" in detail
                else "rate_limited"
                if "429" in detail or "too many requests" in detail
                else "timeout"
                if "timeout" in detail or "timed out" in detail
                else "other"
            )
            reasons[reason] = reasons.get(reason, 0) + 1
        diagnostics["engine_failure_reasons"] = reasons
        if not raw_results and diagnostics["engine_failure_count"]:
            return SearchResult(
                error_message=f"No results returned; {diagnostics['engine_failure_count']} search engines reported failures. Search outcome is inconclusive.",
                error_code="engine_failures",
                diagnostics=diagnostics,
            )
        if not raw_results and data.get("error"):
            return SearchResult(
                error_message="Search backend reported an error without results.",
                error_code="backend_error",
                diagnostics=diagnostics,
            )
        valid = [item for item in raw_results if isinstance(item, Mapping)]
        if raw_results and not valid:
            return SearchResult(
                error_message="Search backend returned malformed result entries.",
                error_code="invalid_results",
                diagnostics=diagnostics,
            )
        return SearchResult(results=SearchResult.from_iterable(valid).results, diagnostics=diagnostics)

    async def _search_text(
        self, query: str, *, category: str, limit: int, engines: list[str] | None = None
    ) -> SearchResult:
        strategy = get_search_strategy(category)
        requested_language = detect_query_language(query)

        ordered_categories = []
        seen_categories: set[str] = set()
        for current_category in (strategy.primary_category, *strategy.fallback_categories):
            if not current_category or current_category in seen_categories:
                continue
            seen_categories.add(current_category)
            ordered_categories.append(current_category)

        result = SearchResult()
        for current_category in ordered_categories:
            result = await self._request_search(
                query,
                category=current_category,
                limit=limit,
                lang=requested_language,
            )
            if result.error_message:
                return result
            filtered = filter_results(
                result,
                category=category,
                limit=limit,
                engines=engines,
                ranking_profile=strategy.ranking_profile,
            )
            if filtered.results:
                return filtered

        return replace(result, results=[])

    async def _filter_image_results(
        self, result: SearchResult, engines: list[str] | None = None, limit: int | None = None
    ) -> SearchResult:
        items = list(result.results)
        if engines:
            items = [item for item in items if item.engine in engines]
        items = [item for item in items if item.img_src][: self.image_candidate_limit]
        valid_items = []
        for item in items:
            try:
                validate_public_url(item.img_src)
                if item.url:
                    validate_public_url(item.url)
                valid_items.append(item)
            except ExternalServiceError:
                continue
        # Metadata only: do not contact untrusted candidates to test availability.
        ranked = rank_image_results(valid_items)
        result_limit = self.image_result_limit if limit is None else min(limit, self.image_result_limit)
        return replace(result, results=ranked[:result_limit])
