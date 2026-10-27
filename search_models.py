import math
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, List, Mapping


@dataclass(slots=True)
class SearchResultItem:
    title: str
    url: str
    img_src: str
    resolution: str
    iframe_src: str
    content: str
    engine: str
    score: float

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "SearchResultItem":
        try:
            score = float(item.get("score", 0.0) or 0.0)
            if not math.isfinite(score):
                score = 0.0
        except (ValueError, TypeError, OverflowError):
            score = 0.0
        return cls(
            title=str(item.get("title", "")),
            url=str(item.get("url", "")),
            img_src=str(item.get("img_src", "")),
            resolution=str(item.get("resolution", "")),
            iframe_src=str(item.get("iframe_src", "")),
            content=str(item.get("content", "")),
            engine=str(item.get("engine", "")),
            score=score,
        )


@dataclass(slots=True)
class SearchResult:
    results: List[SearchResultItem] = field(default_factory=list)
    error_message: str = ""
    error_code: str = ""
    diagnostics: dict = field(default_factory=dict)

    def __iter__(self):
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)

    @property
    def is_empty(self) -> bool:
        return not self.results

    def limited(self, limit: int) -> "SearchResult":
        return replace(self, results=list(self.results[:limit]))

    @classmethod
    def from_iterable(cls, items: Iterable[Mapping[str, Any]]) -> "SearchResult":
        return cls(results=[SearchResultItem.from_mapping(item) for item in items])

    def __str__(self) -> str:
        if self.error_message and not self.results:
            return self.error_message
        if not self.results:
            return "No results."

        formatted_results = [
            f"{idx + 1}. {item.title}\nLink: {item.url}\nContent: {item.content}"
            for idx, item in enumerate(self.results)
        ]
        return "\n".join(formatted_results) if formatted_results else ""
