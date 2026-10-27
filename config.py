from dataclasses import dataclass, field
from typing import Any, Mapping

DEFAULT_SEARXNG_API_URL = "http://127.0.0.1:8080"
DEFAULT_REQUEST_TIMEOUT = 15
DEFAULT_IMAGE_RESULT_LIMIT = 5
DEFAULT_IMAGE_CANDIDATE_LIMIT = 10


@dataclass(frozen=True)
class PluginConfig:
    searxng_api_url: str = DEFAULT_SEARXNG_API_URL
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT
    image_result_limit: int = DEFAULT_IMAGE_RESULT_LIMIT
    image_candidate_limit: int = DEFAULT_IMAGE_CANDIDATE_LIMIT
    search_call_limit: int = 6
    search_empty_limit: int = 3
    search_failure_limit: int = 2
    browser_fallback_enabled: bool = True
    guard_enabled: bool = False
    guard_api_url: str = ""
    guard_auth_token: str = field(default="", repr=False)
    guard_timeout: int = 20
    # Compatibility fields cannot enable old unsafe behaviors.
    enable_random_image: bool = False
    enable_image_title: bool = True
    github_token: str = ""
    default_web_search_enabled: bool = False
    image_delivery_mode: str = "model"
    proxy: None = None

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]):
        return cls(
            searxng_api_url=str(mapping.get("searxng_api_url", DEFAULT_SEARXNG_API_URL)).rstrip("/"),
            request_timeout=max(3, min(int(mapping.get("request_timeout", 15)), 30)),
            image_result_limit=max(1, min(int(mapping.get("image_result_limit", 5)), 10)),
            image_candidate_limit=max(1, min(int(mapping.get("image_candidate_limit", 10)), 20)),
            search_call_limit=max(1, min(int(mapping.get("search_call_limit", 6)), 12)),
            search_empty_limit=max(1, min(int(mapping.get("search_empty_limit", 3)), 6)),
            search_failure_limit=max(1, min(int(mapping.get("search_failure_limit", 2)), 3)),
            browser_fallback_enabled=mapping.get("browser_fallback_enabled", True) is True,
            guard_enabled=mapping.get("guard_enabled", False) is True,
            guard_api_url=str(mapping.get("guard_api_url", "")).strip().rstrip("/"),
            guard_auth_token=str(mapping.get("guard_auth_token", "")).strip(),
            guard_timeout=max(1, min(int(mapping.get("guard_timeout", 20)), 60)),
        )

    @classmethod
    def from_astrbot(cls, config):
        return cls.from_mapping(config)
