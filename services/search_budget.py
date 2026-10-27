"""One incoming event owns one budget shared by all search categories."""

import hashlib
import time
from dataclasses import dataclass, field


@dataclass
class SearchBudget:
    calls: int = 0
    empty_streak: int = 0
    failures: int = 0
    started: float = field(default_factory=time.monotonic)
    seen: set = field(default_factory=set)

    @classmethod
    def for_event(cls, event):
        state = getattr(event, "_guarded_search_budget", None)
        if not isinstance(state, cls):
            state = cls()
            setattr(event, "_guarded_search_budget", state)
        return state

    def claim(self, category, query, *, max_calls=6, max_empty=3, max_failures=2):
        if self.calls >= max_calls or time.monotonic() - self.started > 90:
            return "search_budget_exhausted"
        if self.empty_streak >= max_empty:
            return "repeated_empty_results"
        if self.failures >= max_failures:
            return "repeated_backend_failure"
        key = hashlib.sha256((category + "\\0" + " ".join(str(query).casefold().split())).encode()).digest()
        if key in self.seen:
            return "duplicate_search"
        self.seen.add(key)
        self.calls += 1
        return ""

    def record(self, result):
        if result.error_code and result.error_code != "invalid_query":
            self.failures += 1
        elif not result.error_message and result.is_empty:
            self.empty_streak += 1
        elif result.results:
            self.empty_streak = 0
