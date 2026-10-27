"""Optional fail-closed screening and operator-only connection diagnostics."""

import asyncio
import json
import math
import time
import uuid

import aiohttp

from .network_policy import endpoint

MAX_TEXT_BYTES = 120_000
PROBE_TEXT = "The capital of France is Paris."


class GuardError(Exception):
    def __init__(self, code, message, http_status=None):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


def http_error(status):
    if status in {401, 403}:
        return GuardError(
            "authentication_failed", "Authentication rejected. Check the saved bearer token.", status
        )
    if status == 404:
        return GuardError(
            "endpoint_not_found", "Endpoint not found. Use the base URL without /v1/scan.", status
        )
    if 300 <= status < 400:
        return GuardError(
            "redirect_blocked", "The endpoint redirected. Configure its final base URL directly.", status
        )
    if status == 429:
        return GuardError("busy", "The guard service is busy or rate limited. Retry later.", status)
    if status >= 500:
        return GuardError(
            "service_unavailable", "The guard service reported an error or is not ready.", status
        )
    return GuardError("http_error", "The guard service returned an unexpected HTTP status.", status)


class PromptGuard:
    def __init__(self, *, enabled=False, base_url="", token="", timeout=20):
        self.enabled, self.base_url = enabled, base_url.rstrip("/")
        self.token, self.timeout = token, timeout
        self.slots = asyncio.Semaphore(2)
        self.diagnostic_lock = asyncio.Lock()

    @staticmethod
    def result(state, text=None):
        payload = {"screening": state, "trusted": False}
        if text is not None:
            payload["text"] = text
        else:
            payload["message"] = (
                "External content blocked by Prompt Guard."
                if state == "blocked"
                else "External content withheld because screening is unavailable."
            )
        return json.dumps(payload, ensure_ascii=False)

    def configured(self):
        try:
            parts, _ = endpoint(self.base_url)
            return bool(self.base_url) and not parts.query
        except Exception:
            return False

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @staticmethod
    async def read_json(response):
        if response.status != 200:
            raise http_error(response.status)
        body = bytearray()
        async for chunk in response.content.iter_chunked(8192):
            body.extend(chunk)
            if len(body) > 65536:
                raise GuardError("invalid_response", "Guard response exceeded the size limit.")
        try:
            return json.loads(body)
        except (ValueError, UnicodeError):
            raise GuardError(
                "invalid_response", "Expected a JSON response; check the URL and reverse proxy."
            ) from None

    @staticmethod
    def parse(payload, request_id):
        try:
            rows = payload["results"]
            if not isinstance(rows, list) or len(rows) != 1 or rows[0]["id"] != request_id:
                raise ValueError()
            row = rows[0]
            score, threshold = row["score"], payload["detector"]["threshold"]
            for number in (score, threshold):
                if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= 1:
                    raise ValueError()
            if row["classification"] not in {"benign", "malicious"}:
                raise ValueError()
            if type(row["chunks_scanned"]) is not int or row["chunks_scanned"] < 1:
                raise ValueError()
        except (KeyError, TypeError, ValueError, IndexError):
            raise GuardError(
                "invalid_response",
                "Incompatible scan response. Expected one matching result with classification, score, chunks_scanned and detector.threshold.",
            ) from None
        return {
            "blocked": row["classification"] == "malicious" or score >= threshold,
            "classification": row["classification"],
            "score": score,
            "threshold": threshold,
        }

    async def scan_document(self, text):
        request_id = uuid.uuid4().hex
        async with (
            self.slots,
            aiohttp.ClientSession(
                trust_env=False, timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session,
        ):
            async with session.post(
                self.base_url + "/v1/scan",
                headers=self.headers,
                json={
                    "inputs": [{"id": request_id, "text": text, "source": "web"}],
                    "options": {"include_findings": False, "include_excerpts": False},
                },
                allow_redirects=False,
            ) as response:
                payload = await self.read_json(response)
        return self.parse(payload, request_id)

    async def scan(self, text):
        return (await self.scan_document(text))["blocked"]

    async def review(self, text):
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            return self.result("unavailable")
        if not self.enabled:
            return self.result("disabled", text)
        if not self.configured():
            return self.result("unavailable")
        try:
            async with asyncio.timeout(self.timeout):
                blocked = await self.scan(text)
            return self.result("blocked" if blocked else "accepted", None if blocked else text)
        except Exception:
            return self.result("unavailable")

    async def diagnostics(self):
        """Fixed probe only. Never accepts a caller-supplied URL, token or prompt."""
        start = time.monotonic()
        report = {"ok": False, "enabled": self.enabled, "token_configured": bool(self.token), "checks": []}
        if not self.configured():
            return {
                **report,
                "code": "configuration_missing",
                "message": "Save a valid Prompt Guard base URL, then reload the plugin.",
            }
        if self.diagnostic_lock.locked():
            return {**report, "code": "busy", "message": "A connection test is already running."}
        stage = "health"
        try:
            async with self.diagnostic_lock, asyncio.timeout(self.timeout):
                async with aiohttp.ClientSession(
                    trust_env=False, timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as session:
                    for stage, path, headers in (
                        ("health", "/health", {}),
                        ("readiness", "/ready", self.headers),
                    ):
                        async with session.get(
                            self.base_url + path, headers=headers, allow_redirects=False
                        ) as response:
                            if response.status != 200:
                                raise http_error(response.status)
                            # Liveness/readiness bodies are not returned or logged.
                            report["checks"].append({"stage": stage, "ok": True, "http_status": 200})
                stage = "scan"
                verdict = await self.scan_document(PROBE_TEXT)
                report["checks"].append({"stage": stage, "ok": True, "http_status": 200, **verdict})
                report.update(
                    ok=True,
                    code="connected",
                    message=(
                        "Connected and authenticated. The fixed probe was flagged; review detector settings."
                        if verdict["blocked"]
                        else "Connected: health, authenticated readiness and scan response passed."
                    ),
                )
        except GuardError as error:
            report.update(code=error.code, message=error.message)
            report["checks"].append({"stage": stage, "ok": False, "http_status": error.http_status})
        except TimeoutError:
            report.update(
                code="timeout",
                message="Connection test timed out. Check connectivity, timeout and service load.",
            )
            report["checks"].append({"stage": stage, "ok": False})
        except aiohttp.ClientConnectorCertificateError:
            report.update(code="tls_error", message="TLS certificate validation failed.")
            report["checks"].append({"stage": stage, "ok": False})
        except aiohttp.ClientConnectorError:
            report.update(
                code="connection_failed",
                message="Could not connect. Check hostname, port, container routing and firewall.",
            )
            report["checks"].append({"stage": stage, "ok": False})
        except Exception:
            report.update(
                code="connection_failed",
                message="Connection test failed. Check service connectivity and configuration.",
            )
            report["checks"].append({"stage": stage, "ok": False})
        report["elapsed_ms"] = round((time.monotonic() - start) * 1000)
        return report
