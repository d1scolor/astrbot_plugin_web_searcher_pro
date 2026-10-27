from astrbot_plugin_web_searcher_pro.config import PluginConfig


class DummyConfig(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def test_plugin_config_reads_defaults():
    config = PluginConfig.from_mapping(DummyConfig())

    assert config.searxng_api_url == "http://127.0.0.1:8080"
    assert config.enable_random_image is False
    assert config.enable_image_title is True
    assert config.github_token == ""
    assert config.default_web_search_enabled is False
    assert config.image_delivery_mode == "model"


def test_plugin_config_reads_default_web_search_toggle():
    config = PluginConfig.from_mapping(DummyConfig(default_web_search_enabled=True))

    assert config.default_web_search_enabled is False


def test_plugin_config_reads_image_delivery_mode():
    config = PluginConfig.from_mapping(DummyConfig(image_delivery_mode="user"))

    assert config.image_delivery_mode == "model"


def test_plugin_config_rejects_invalid_image_delivery_mode():
    config = PluginConfig.from_mapping(DummyConfig(image_delivery_mode="invalid"))

    assert config.image_delivery_mode == "model"


def test_limits_and_credentials_are_not_inherited():
    config = PluginConfig.from_mapping(
        {
            "image_result_limit": 999,
            "image_candidate_limit": 999,
            "github_token": "synthetic-token",
            "guard_auth_token": "synthetic-guard",
        }
    )
    assert config.image_result_limit == 10
    assert config.image_candidate_limit == 20
    assert config.github_token == ""
    assert "synthetic-guard" not in repr(config)
