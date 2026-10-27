import asyncio
import importlib
import re
import sys
import types
from pathlib import Path

MAIN_MODULE_NAME = "data.plugins.astrbot_plugin_web_searcher_pro.main"


def _stub_module(monkeypatch, name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _import_plugin_main(monkeypatch):
    project_root = Path(__file__).resolve().parents[4]
    plugin_root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        sys,
        "path",
        [entry for entry in sys.path if Path(entry or ".").resolve() != plugin_root],
    )
    monkeypatch.syspath_prepend(str(project_root))

    for module_name in [
        MAIN_MODULE_NAME,
        "astrbot",
        "astrbot.api",
        "astrbot.api.event",
        "astrbot.api.event.filter",
        "astrbot.api.star",
        "astrbot.core",
        "astrbot.core.message",
        "astrbot.core.message.components",
        "astrbot.core.message.message_event_result",
        "aiohttp",
        "bs4",
        "PIL",
        "readability",
    ]:
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    _stub_module(monkeypatch, "astrbot")
    api = _stub_module(monkeypatch, "astrbot.api")
    event = _stub_module(monkeypatch, "astrbot.api.event")
    _stub_module(monkeypatch, "astrbot.api.event.filter")
    star = _stub_module(monkeypatch, "astrbot.api.star")
    _stub_module(monkeypatch, "astrbot.core")
    _stub_module(monkeypatch, "astrbot.core.message")
    components = _stub_module(monkeypatch, "astrbot.core.message.components")
    message_event_result = _stub_module(monkeypatch, "astrbot.core.message.message_event_result")
    aiohttp = _stub_module(monkeypatch, "aiohttp")
    bs4 = _stub_module(monkeypatch, "bs4")
    pil = _stub_module(monkeypatch, "PIL")
    readability = _stub_module(monkeypatch, "readability")

    class DummyStar:
        def __init__(self, context=None):
            self.context = context

    class DummyContext:
        pass

    class DummyConfig(dict):
        pass

    def register(*args, **kwargs):
        def decorator(obj):
            return obj

        return decorator

    def llm_tool(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def command(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    class DummyLogger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    class DummyClientError(Exception):
        pass

    class DummyClientTimeout:
        def __init__(self, *args, **kwargs):
            pass

    class DummyClientSession:
        def __init__(self, *args, **kwargs):
            pass

    class DummyDocument:
        def __init__(self, html):
            self.html = html

        def summary(self):
            return self.html

    api.__dict__.update(
        logger=DummyLogger(),
        AstrBotConfig=DummyConfig,
        llm_tool=llm_tool,
        command=command,
        __all__=["logger", "AstrBotConfig", "llm_tool", "command"],
    )
    event.__dict__.update(AstrMessageEvent=type("AstrMessageEvent", (), {}))
    star.__dict__.update(Context=DummyContext, Star=DummyStar, register=register)
    components.__dict__.update(
        Image=type(
            "Image",
            (),
            {
                "fromBase64": staticmethod(lambda value: value),
                "fromURL": staticmethod(lambda value: value),
            },
        ),
        Node=type("Node", (), {}),
        Nodes=type("Nodes", (), {}),
        Plain=type("Plain", (), {}),
    )
    message_event_result.__dict__.update(MessageChain=list)
    aiohttp.__dict__.update(
        ClientError=DummyClientError,
        ClientTimeout=DummyClientTimeout,
        ClientSession=DummyClientSession,
    )
    bs4.__dict__.update(BeautifulSoup=type("BeautifulSoup", (), {}))
    pil.__dict__.update(Image=type("PilImage", (), {"open": staticmethod(lambda value: value)}))
    readability.__dict__.update(Document=DummyDocument)

    return importlib.import_module(MAIN_MODULE_NAME)


def test_plugin_main_imports_as_package(monkeypatch):
    module = _import_plugin_main(monkeypatch)

    assert hasattr(module, "WebSearcherPro")


def test_llm_tools_keep_parameter_docstrings(monkeypatch):
    module = _import_plugin_main(monkeypatch)
    expected_parameters = {
        "search_general": "query",
        "search_images": "query",
        "search_videos": "query",
        "search_news": "query",
        "search_science": "query",
        "search_music": "query",
        "search_technical": "query",
        "search_academic": "query",
        "search_map": "query",
        "search_files": "query",
        "search_social": "query",
        "search_books": "query",
        "fetch_website_content": "url",
        "search_github_repo": "query",
    }

    for method_name, parameter_name in expected_parameters.items():
        method = getattr(module.WebSearcherPro, method_name)
        docstring = method.__doc__

        assert docstring, f"{method_name} should keep a docstring for tool metadata"
        assert "Args:" in docstring, f"{method_name} should document parameters for the LLM tool"
        assert re.search(rf"{parameter_name}\s*\((?:str|string)\)\s*:", docstring), (
            f"{method_name} should describe the {parameter_name} parameter"
        )


def test_command_handlers_keep_docstrings_for_router_metadata(monkeypatch):
    module = _import_plugin_main(monkeypatch)
    expected_phrases = {
        "websearch": "Report search configuration.",
        "search_aur": "Only use this command when the user explicitly asks for an Arch Linux or AUR package.",
        "github_search": "Only use this command when the user explicitly asks to run the /github command.",
    }

    for method_name, expected_phrase in expected_phrases.items():
        method = getattr(module.WebSearcherPro, method_name)
        docstring = method.__doc__

        assert docstring, f"{method_name} should keep a docstring for command routing metadata"
        assert expected_phrase in docstring


class DummyProviderConfig(dict):
    def __init__(self):
        super().__init__(provider_settings={"web_search": False})
        self.saved = False

    def save_config(self):
        self.saved = True


class DummyContext:
    def __init__(self):
        self.config = DummyProviderConfig()
        self.activated_tools = []
        self.deactivated_tools = []

    def get_config(self):
        return self.config

    def activate_llm_tool(self, tool_name: str):
        self.activated_tools.append(tool_name)

    def deactivate_llm_tool(self, tool_name: str):
        self.deactivated_tools.append(tool_name)


def test_chat_toggle_cannot_modify_global_config(monkeypatch):
    from astrbot_plugin_web_searcher_pro.services.prompt_guard import PromptGuard

    module = _import_plugin_main(monkeypatch)
    plugin = object.__new__(module.WebSearcherPro)
    plugin.context = DummyContext()
    plugin.guard = PromptGuard()
    event = types.SimpleNamespace(plain_result=lambda text: text)

    async def invoke():
        return [message async for message in plugin.websearch(event, "on")]

    messages = asyncio.run(invoke())
    assert "cannot change global settings" in messages[0]
    assert plugin.context.config["provider_settings"]["web_search"] is False
    assert not plugin.context.config.saved
    assert not plugin.context.activated_tools and not plugin.context.deactivated_tools
    assert not hasattr(plugin, "_set_websearch_status")


def test_new_text_search_tools_forward_category_and_empty_message(monkeypatch):
    module = _import_plugin_main(monkeypatch)
    expectations = {
        "search_map": ("map", module.MAP_EMPTY_MESSAGE),
        "search_files": ("files", module.FILES_EMPTY_MESSAGE),
        "search_social": ("social", module.SOCIAL_EMPTY_MESSAGE),
        "search_books": ("books", module.BOOKS_EMPTY_MESSAGE),
    }

    for method_name, (expected_category, expected_empty_message) in expectations.items():
        plugin = object.__new__(module.WebSearcherPro)
        calls = []

        async def fake_search_text_category(
            query: str, *, category: str, empty_message: str, limit: int = 5
        ) -> str:
            calls.append((query, category, empty_message, limit))
            return f"forwarded:{category}"

        monkeypatch.setattr(plugin, "_search_text_category", fake_search_text_category, raising=False)

        result = asyncio.run(getattr(module.WebSearcherPro, method_name)(plugin, None, "test query"))

        assert result == f"forwarded:{expected_category}"
        assert calls == [("test query", expected_category, expected_empty_message, 5)]


def test_search_images_returns_model_text_without_yielding(monkeypatch):
    module = _import_plugin_main(monkeypatch)
    plugin = object.__new__(module.WebSearcherPro)
    plugin.plugin_config = types.SimpleNamespace(
        image_result_limit=2,
        image_delivery_mode="model",
        enable_random_image=False,
        enable_image_title=True,
    )
    from astrbot_plugin_web_searcher_pro.search_models import SearchResult
    from astrbot_plugin_web_searcher_pro.services.prompt_guard import PromptGuard

    plugin.guard = PromptGuard()
    plugin.searxng_service = types.SimpleNamespace()
    plugin.image_service = types.SimpleNamespace()
    sent_messages = []

    class DummyEvent:
        async def send(self, message):
            sent_messages.append(message)

    async def fake_search(*args, **kwargs):
        return SearchResult.from_iterable(
            [
                {
                    "title": "Apple image",
                    "url": "https://example.com/page",
                    "img_src": "https://example.com/apple.jpg",
                    "resolution": "800x600",
                    "content": "Apple picture",
                    "engine": "demo",
                    "score": 1.0,
                }
            ]
        )

    plugin.searxng_service.search = fake_search

    result = asyncio.run(module.WebSearcherPro.search_images(plugin, DummyEvent(), "苹果"))

    assert "Apple image" in result
    assert "Image: https://example.com/apple.jpg" in result
    assert sent_messages == []
    import json

    payload = json.loads(result)
    assert "comfy_send_images" in payload["delivery_guidance"]
    assert payload["trusted"] is False


def test_every_external_text_entrypoint_is_guarded(monkeypatch):
    from astrbot_plugin_web_searcher_pro.search_models import SearchResult
    from astrbot_plugin_web_searcher_pro.services.prompt_guard import PromptGuard

    module = _import_plugin_main(monkeypatch)
    plugin = object.__new__(module.WebSearcherPro)
    plugin.plugin_config = types.SimpleNamespace(image_result_limit=5)
    plugin.guard = PromptGuard(enabled=True, base_url="http://guard.example")
    scanned = []

    async def scan(text):
        scanned.append(text)
        return True

    plugin.guard.scan = scan

    async def search(*args, **kwargs):
        return SearchResult.from_iterable(
            [
                {
                    "title": "UNTRUSTED_MARKER",
                    "url": "https://example.org",
                    "img_src": "https://example.org/a.png",
                    "content": "external",
                }
            ]
        )

    async def external(*args, **kwargs):
        return "UNTRUSTED_MARKER external content"

    plugin.searxng_service = types.SimpleNamespace(search=search)
    plugin.web_fetch_service = types.SimpleNamespace(fetch=external)
    plugin.github_service = types.SimpleNamespace(search=external)
    plugin.aur_service = types.SimpleNamespace(search=external)
    event = types.SimpleNamespace(plain_result=lambda text: text)

    async def invoke():
        tools = [
            "search_general",
            "search_images",
            "search_videos",
            "search_news",
            "search_science",
            "search_music",
            "search_technical",
            "search_academic",
            "search_map",
            "search_files",
            "search_social",
            "search_books",
            "fetch_website_content",
            "search_github_repo",
        ]
        for name in tools:
            result = await getattr(plugin, name)(event, "query")
            assert '"screening": "blocked"' in result
            assert "UNTRUSTED_MARKER" not in result
        for name in ("search_aur", "github_search"):
            outputs = [text async for text in getattr(plugin, name)(event, "query")]
            assert len(outputs) == 1
            assert '"screening": "blocked"' in outputs[0]
            assert "UNTRUSTED_MARKER" not in outputs[0]

    asyncio.run(invoke())
    assert len(scanned) == 16
    assert all("UNTRUSTED_MARKER" in text for text in scanned)


def test_diagnostic_endpoint_requires_dashboard_identity(monkeypatch):
    module = _import_plugin_main(monkeypatch)
    web = types.ModuleType("astrbot.api.web")
    web.request = types.SimpleNamespace(username=None)
    web.json_response = lambda data, **kwargs: data
    web.error_response = lambda message, **kwargs: {"error": message, "status_code": kwargs["status_code"]}
    monkeypatch.setitem(sys.modules, "astrbot.api.web", web)
    plugin = object.__new__(module.WebSearcherPro)
    calls = []

    async def diagnose():
        calls.append(True)
        return {"ok": True}

    plugin.guard = types.SimpleNamespace(diagnostics=diagnose)
    result = asyncio.run(plugin.test_guard_connection())
    assert result["status_code"] == 403 and not calls
    web.request.username = "dashboard-test-user"
    assert asyncio.run(plugin.test_guard_connection()) == {"ok": True}
    assert calls == [True]
