"""Optional fail-closed screening before external text enters an agent response."""

import asyncio
import json
import math
import uuid

import aiohttp

from .network_policy import endpoint

MAX_TEXT_BYTES = 120_000


class PromptGuard:
    def __init__(self, *, enabled=False, base_url="", token="", timeout=20):
        self.enabled, self.base_url = enabled, base_url.rstrip("/")
        self.token, self.timeout = token, timeout
        self.slots = asyncio.Semaphore(2)

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

    async def scan(self, text):
        request_id = uuid.uuid4().hex
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with (
            self.slots,
            aiohttp.ClientSession(
                trust_env=False, timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session,
        ):
            async with session.post(
                self.base_url + "/v1/scan",
                headers=headers,
                json={
                    "inputs": [{"id": request_id, "text": text, "source": "web"}],
                    "options": {"include_findings": False, "include_excerpts": False},
                },
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise ValueError("Guard request failed")
                body = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    body.extend(chunk)
                    if len(body) > 65536:
                        raise ValueError("Guard response too large")
                payload = json.loads(body)
        rows = payload["results"]
        if not isinstance(rows, list) or len(rows) != 1 or rows[0]["id"] != request_id:
            raise ValueError("Incomplete guard response")
        row = rows[0]
        score, threshold = row["score"], payload["detector"]["threshold"]
        for number in (score, threshold):
            if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= 1:
                raise ValueError("Invalid guard score")
        if row["classification"] not in {"benign", "malicious"}:
            raise ValueError("Invalid classification")
        if type(row["chunks_scanned"]) is not int or row["chunks_scanned"] < 1:
            raise ValueError("No confirmed scanned chunks")
        return row["classification"] == "malicious" or score >= threshold

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
