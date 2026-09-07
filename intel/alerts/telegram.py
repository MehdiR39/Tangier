"""Telegram sender: HTML with plain-text fallback, 4096-char truncation, rate limited.

Ported from ``scripts/daily_report.py`` (send_telegram) to async httpx. Uses the same
``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID`` variables (``INTEL_TELEGRAM_*`` override).
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from intel.settings import Settings
from intel.utils.ratelimit import RateLimiter

log = logging.getLogger(__name__)
MAX_LEN = 4096


def strip_html(text: str) -> str:
    return re.sub(r"<[^>\n]+>", "", text).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


class TelegramSender:
    def __init__(self, settings: Settings) -> None:
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.dry_run = settings.telegram_dry_run or not (self.token and self.chat_id)
        self.limiter = RateLimiter(settings.limits.telegram_rps, burst=3, name="telegram")
        self._client = httpx.AsyncClient(timeout=30, headers={"User-Agent": settings.user_agent})
        if self.dry_run and not settings.telegram_dry_run:
            log.warning("Telegram credentials not configured: alerts will be logged only")

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    async def close(self) -> None:
        await self._client.aclose()

    async def _post(self, text: str, html: bool) -> dict[str, Any]:
        params: dict[str, Any] = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": "true"}
        if html:
            params["parse_mode"] = "HTML"
        await self.limiter.acquire()
        resp = await self._client.post(f"https://api.telegram.org/bot{self.token}/sendMessage", data=params)
        if resp.status_code == 429:
            retry = float((resp.json().get("parameters") or {}).get("retry_after", 5)) if resp.headers.get("content-type", "").startswith("application/json") else 5.0
            self.limiter.penalize(retry)
        resp.raise_for_status()
        return resp.json()

    async def send(self, text: str) -> tuple[bool, str | None, str | None]:
        """Return (ok, message_id, error)."""
        if len(text) > MAX_LEN:
            text = text[: MAX_LEN - 16] + "\n…(truncated)"
        if self.dry_run:
            log.info("[telegram dry-run]\n%s", strip_html(text))
            return True, None, None
        try:
            data = await self._post(text, html=True)
            return bool(data.get("ok")), str((data.get("result") or {}).get("message_id")), None
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:200]
            log.warning("telegram HTML send failed %s: %s — retrying as plain text", exc.response.status_code, body)
            try:
                data = await self._post(strip_html(text), html=False)
                return bool(data.get("ok")), str((data.get("result") or {}).get("message_id")), None
            except Exception as exc2:  # noqa: BLE001
                log.error("telegram plain retry failed: %s", exc2)
                return False, None, str(exc2)[:200]
        except Exception as exc:  # noqa: BLE001
            log.error("telegram send failed: %s", exc)
            return False, None, str(exc)[:200]
