# Guarded SearXNG Search for AstrBot

Fork of [WebSearcherPro by buding](https://github.com/zouyonghe/astrbot_plugin_web_searcher_pro),
maintained here with public-network-only page fetching and optional Prompt Guard screening.
Target: AstrBot 4.29.3, Python 3.11 or newer. Version 1.2.1.

## Configure

Install/update from **this fork**:

```text
https://github.com/d1scolor/astrbot_plugin_web_searcher_pro
```

Remove/disable the original search integration so only this fork's search tools are
available. Existing SearXNG endpoint settings carry over. The plugin can load before
Prompt Guard is configured; it does not call services at startup.

| Setting | Default | Purpose |
| --- | --- | --- |
| `searxng_api_url` | Local endpoint placeholder | Your administrator-configured SearXNG base URL, reachable from AstrBot's container. JSON must be enabled. |
| `guard_enabled` | `false` | Optional screening. Enable after configuring the endpoint and token. |
| `guard_api_url` | Empty | Prompt Guard base URL, without `/v1/scan`. |
| `guard_auth_token` | Empty | Bearer token stored in AstrBot's local configuration. Never commit or share it. |
| `guard_timeout` | 20 | Screening deadline, including admission wait; range 1–60 seconds. |
| `request_timeout` | 15 | Network deadline; range 3–30 seconds. |
| `image_result_limit` | 5 | Returned metadata entries; hard maximum 10. |
| `image_candidate_limit` | 10 | Metadata candidates considered; hard maximum 20. |

Use the active bot/persona's tool allowlist to enable only the required tools. Keep
AstrBot's separate built-in search disabled if all searches must pass this integration.
This plugin does not modify global configuration or activate/deactivate tools.
`/websearch` now only reports configuration; on/off arguments cannot change settings.
Older `default_web_search_enabled`, image-delivery and GitHub-token settings are ignored.
Administrator GitHub credentials are never used for chat-controlled repository queries.

## Connection test in the Dashboard

After saving configuration and reloading the plugin, open its detail page and select
**Prompt Guard connection test / Prompt Guard 连接测试** under plugin Views. Click
**Test connection**. No extra service or port is required.

The test uses loaded/saved settings, not unsaved form values. It checks `/health`,
authenticated `/ready`, then `/v1/scan` using one fixed harmless sentence. It works
with `guard_enabled=false`, so connectivity can be checked before enabling screening.
Results identify authentication errors, missing endpoints, redirects, timeouts,
connection/TLS failures and incompatible response formats. The token and raw server
bodies are never returned to the browser. A flagged probe is reported separately from
a connection failure. Diagnostic success does not certify detector accuracy.

The test endpoint is a POST-only authenticated Dashboard API. It is not an LLM tool,
accepts no endpoint/token/text overrides, and cannot be used by a chat member as a proxy.
If search still returns `unavailable` after a successful connection test, check search
connectivity and content-size limits: those can also cause the content to be withheld.

## Behavior

The existing `searxng_*` search categories, page-fetch and public GitHub lookup tools
are retained. Search queries are limited to 2000 characters. Image search returns URLs,
titles and descriptions to the model; it never downloads, HEAD-probes or sends candidate
images to users. For user requests to find/show pictures, its tool schema and successful
results direct the agent to select up to three direct image URLs and call
`comfy_send_images` from ComfyUI Direct **v0.4.0+** for actual attachments. Enable that
tool alongside image search. Links are appropriate when explicitly requested; generation
research candidates stay unsent. Selection and tool routing still depend on the model;
this plugin does not automatically download/post every candidate. Blocked or unavailable
screening responses receive no delivery guidance. Image engines
follow the instance's configured category rather than a hardcoded Google/Bing allowlist.

All external text returned by the plugin's LLM tools and external-content commands
passes through one response boundary. This includes search results, image metadata,
extracted pages, GitHub descriptions/READMEs, AUR descriptions and external error text.
The complete formatted result is scanned as one document; a detection withholds the
whole response. Token-window scanning is performed by the guard server. Content is not
silently truncated to evade scanning; responses over 120,000 UTF-8 bytes are withheld.

Tool output is a JSON envelope:

```json
{"screening":"accepted","trusted":false,"text":"External result text"}
```

| `screening` | Meaning |
| --- | --- |
| `disabled` | Guard is off. Text is returned explicitly unscanned. |
| `accepted` | Guard returned a matching benign result below its reported threshold. Content remains untrusted data. |
| `blocked` | Suspected injection; no original content is returned. |
| `unavailable` | Guard/configuration/network failure or size limit; no original content is returned. |

When screening is enabled, bad authentication, redirects, timeouts, HTTP errors,
malformed JSON, missing/duplicate/mismatched results, invalid scores and unconfirmed
chunk scanning all fail closed. There is no implicit fallback to unscanned output.
No guard request includes conversation history, persona instructions or credentials
inside the text payload; only the tool result is scanned. As with any fetched content,
a page could itself contain sensitive information. Query/URL logging remains enabled
as in upstream, and AstrBot may independently log tool calls/results.

## Network boundary

Public fetching is restricted to HTTP(S) on ports 80/443, without embedded credentials.
Loopback, private, link-local, reserved/multicast and transition addresses are rejected.
DNS records are checked by the connector resolver and cached DNS is disabled; redirects
are followed manually and every destination is checked. Proxies and environment proxy
inheritance are disabled because a remote resolver could bypass this policy.

Only two administrator-configured infrastructure routes may use private networks:

- SearXNG: GET to the configured base's `/search` path, without redirects.
- Prompt Guard: POST to the configured base's `/v1/scan`, without redirects. The bearer
  token is sent only on this connection.

Neither endpoint can be supplied or changed through model tool arguments. Public and
infrastructure clients are separate. HTTP responses are limited to 2 MiB and requests
have concurrency/deadline limits. These are application-layer restrictions, not an OS
firewall or a guarantee about unrelated plugins and tools.

The guard screens **text only**, including image metadata. This release does not OCR
images or protect other plugins' image/vision paths. Accepted results never authorize
shell access, configuration changes, private-network requests or other privileged actions.

## Validate on your deployment

1. Set SearXNG and test an ordinary web/image search with the guard off; results must
   report `disabled`. No reference images should be posted to the chat automatically.
2. Configure Prompt Guard URL/token, enable it, save and reload.
3. Search again; the tool response should report `accepted` for ordinary content.
4. Temporarily enter an invalid guard token, reload and search: the response must be
   `unavailable`, with no search text. Restore the token locally afterward.
5. Request a localhost/private page fetch: it must be blocked without a target request.
6. Check the actual tool inventory. The plugin cannot guard a separate built-in search,
   another fetch plugin, an MCP server, or content already in conversation history.

Automated tests use fake HTTP plus local mock servers. No test uses production tokens,
performs internal-network probes or sends QQ messages. The deployed guard's unauthenticated
health endpoint was reachable during development; authenticated deployment scanning still
requires local configuration and validation.

```sh
uv sync --group dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```
