"""Telegram: the first real customer-message delivery adapter.

A seam entirely separate from ``PaymentProvider`` (see ``protocols.
MessageDeliveryAdapter``) - Razorpay creates/confirms the recovery link;
Telegram only ever delivers an already-staged, already-authorized template
draft, with the confirmed checkout URL appended HERE, at the delivery
boundary (never inside the stored/audited draft, never generated or seen by
Hermes).

Disabled by default. Configuration is read ONLY from three environment
variables - ``TELEGRAM_ENABLED`` / ``TELEGRAM_BOT_TOKEN`` /
``TELEGRAM_CHAT_ID`` - never from a file, never printed, never logged,
never persisted, never returned in any receipt. Missing or disabled
configuration must never silently claim delivery: :class:`NullTelegramAdapter`
(and :class:`TelegramAdapter` itself, when unconfigured) always report
``"failed"`` with a fixed, non-secret reason.

No network call happens at import time or at construction; a real HTTP POST
only happens inside :meth:`TelegramAdapter.deliver`, and only via
``urllib`` (stdlib only, no new dependency). Tests inject ``http_post``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .types import DeliveryOutcome, DeliveryReceipt

API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT_S = 15.0

# Fixed, non-secret failure/uncertain reason categories - never a raw
# exception message or the provider's own "description" text.
_REASON_DISABLED = "telegram_disabled_or_unconfigured"
_REASON_NETWORK = "network_error"
_REASON_TIMEOUT = "timeout"
_REASON_MALFORMED = "malformed_response"
_REASON_MISSING_MESSAGE_ID = "missing_message_id"
_REASON_REJECTED = "telegram_api_rejected"
_REASON_UNEXPECTED = "unexpected_error"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _clean(value: str | None) -> str | None:
    v = (value or "").strip()
    return v or None


@dataclass(frozen=True)
class TelegramConfig:
    """Read-only snapshot of the three supported environment variables.
    Never logged or printed as a whole - see :meth:`describe`, which never
    includes the token or the full chat id."""

    enabled: bool
    bot_token: str | None
    chat_id: str | None

    @classmethod
    def from_env(cls, env: "dict[str, str] | None" = None) -> "TelegramConfig":
        e = env if env is not None else os.environ
        return cls(
            enabled=(e.get("TELEGRAM_ENABLED") or "").strip().lower() in _TRUE_VALUES,
            bot_token=_clean(e.get("TELEGRAM_BOT_TOKEN")),
            chat_id=_clean(e.get("TELEGRAM_CHAT_ID")),
        )

    @property
    def ready(self) -> bool:
        """True only when delivery is explicitly enabled AND both
        credentials are present. Never True on a missing/blank value."""
        return bool(self.enabled and self.bot_token and self.chat_id)

    def describe(self) -> dict[str, Any]:
        """Sanitized status for display - presence/shape only, never a
        secret value in full."""
        return {
            "enabled": self.enabled,
            "bot_token_present": bool(self.bot_token),
            "chat_id_present": bool(self.chat_id),
            "ready": self.ready,
        }


class NullTelegramAdapter:
    """Used whenever Telegram is disabled or unconfigured. Every call
    reports ``"failed"`` with a fixed reason - it can never claim a message
    was delivered."""

    def deliver(self, *, text: str) -> DeliveryReceipt:
        return DeliveryReceipt(outcome=DeliveryOutcome.FAILED.value, reason=_REASON_DISABLED)


def _default_http_post(url: str, payload: dict, timeout_s: float) -> Any:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 - fixed https API host
        return json.loads(resp.read().decode("utf-8"))


class TelegramAdapter:
    """The real adapter: one ``sendMessage`` POST per :meth:`deliver` call.

    ``http_post`` is the test seam - ``(url, payload, timeout_s) -> dict``,
    defaulting to a real bounded ``urllib`` POST. No network call happens
    until :meth:`deliver` is actually called.
    """

    def __init__(
        self,
        config: TelegramConfig,
        *,
        http_post: "Callable[[str, dict, float], Any] | None" = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._config = config
        self._http_post = http_post or _default_http_post
        self._timeout_s = float(timeout_s)

    def deliver(self, *, text: str) -> DeliveryReceipt:
        if not self._config.ready:
            return DeliveryReceipt(outcome=DeliveryOutcome.FAILED.value, reason=_REASON_DISABLED)
        url = f"{API_BASE}/bot{self._config.bot_token}/sendMessage"
        payload = {"chat_id": self._config.chat_id, "text": text}
        try:
            resp = self._http_post(url, payload, self._timeout_s)
        except TimeoutError:
            return DeliveryReceipt(outcome=DeliveryOutcome.UNCERTAIN.value, reason=_REASON_TIMEOUT)
        except (urllib.error.URLError, OSError):
            return DeliveryReceipt(outcome=DeliveryOutcome.UNCERTAIN.value, reason=_REASON_NETWORK)
        except Exception:  # noqa: BLE001 - never surface a raw exception message
            return DeliveryReceipt(outcome=DeliveryOutcome.UNCERTAIN.value, reason=_REASON_UNEXPECTED)

        if not isinstance(resp, dict):
            return DeliveryReceipt(outcome=DeliveryOutcome.UNCERTAIN.value, reason=_REASON_MALFORMED)
        if resp.get("ok") is not True:
            # Telegram explicitly rejected the call (bad token, blocked chat,
            # bad request, ...) - a clear failure, never "uncertain". The
            # provider's own "description" text is never surfaced.
            return DeliveryReceipt(outcome=DeliveryOutcome.FAILED.value, reason=_REASON_REJECTED)
        result = resp.get("result")
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if not isinstance(message_id, int) or isinstance(message_id, bool):
            return DeliveryReceipt(
                outcome=DeliveryOutcome.UNCERTAIN.value, reason=_REASON_MISSING_MESSAGE_ID
            )
        return DeliveryReceipt(outcome=DeliveryOutcome.SENT.value, message_id=str(message_id))


def _default_http_get(url: str, timeout_s: float) -> Any:
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def verify_bot(
    config: TelegramConfig, *, http_get: "Callable[[str, float], Any] | None" = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Call ``getMe`` to confirm the bot token is valid. Returns
    ``{"ok": True, "username": ..., "bot_id": ...}`` on success, or
    ``{"ok": False, "reason": <fixed category>}`` - never the token, never a
    raw provider error message. Used only by ``scripts/telegram_setup.py``."""
    if not config.bot_token:
        return {"ok": False, "reason": "missing_bot_token"}
    get = http_get or _default_http_get
    url = f"{API_BASE}/bot{config.bot_token}/getMe"
    try:
        resp = get(url, timeout_s)
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": _REASON_NETWORK}
    if not isinstance(resp, dict) or resp.get("ok") is not True:
        return {"ok": False, "reason": _REASON_REJECTED}
    result = resp.get("result")
    if not isinstance(result, dict):
        return {"ok": False, "reason": _REASON_MALFORMED}
    return {
        "ok": True,
        "username": result.get("username"),
        "bot_id": result.get("id"),
    }


def fetch_chat_id_candidates(
    config: TelegramConfig, *, http_get: "Callable[[str, float], Any] | None" = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Call ``getUpdates`` and extract candidate chat ids the user could
    paste into ``.env`` - after they have messaged the bot at least once.
    Returns ``{"ok": True, "candidates": [{"chat_id": ..., "first_name": ...,
    "is_group": bool}, ...]}`` (each field sanitized/bounded; no message
    text, no username beyond a display first name) or a fixed failure
    reason. Never writes anything - the user still copies the value
    themselves."""
    if not config.bot_token:
        return {"ok": False, "reason": "missing_bot_token"}
    get = http_get or _default_http_get
    url = f"{API_BASE}/bot{config.bot_token}/getUpdates"
    try:
        resp = get(url, timeout_s)
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": _REASON_NETWORK}
    if not isinstance(resp, dict) or resp.get("ok") is not True:
        return {"ok": False, "reason": _REASON_REJECTED}
    results = resp.get("result")
    if not isinstance(results, list):
        return {"ok": False, "reason": _REASON_MALFORMED}
    seen: dict[int, dict[str, Any]] = {}
    for update in results:
        if not isinstance(update, dict):
            continue
        msg = update.get("message")
        if not isinstance(msg, dict):
            continue
        chat = msg.get("chat")
        if not isinstance(chat, dict):
            continue
        chat_id = chat.get("id")
        if not isinstance(chat_id, int) or isinstance(chat_id, bool):
            continue
        seen[chat_id] = {
            "chat_id": chat_id,
            "first_name": chat.get("first_name") if isinstance(chat.get("first_name"), str) else None,
            "is_group": chat.get("type") != "private",
        }
    return {"ok": True, "candidates": list(seen.values())}


def build_delivery_adapter(env: "dict[str, str] | None" = None) -> "TelegramAdapter | NullTelegramAdapter":
    """The adapter this build actually wires up: a real ``TelegramAdapter``
    when configured+enabled, otherwise the safe :class:`NullTelegramAdapter`
    (never a silent no-op that could be mistaken for success)."""
    config = TelegramConfig.from_env(env)
    return TelegramAdapter(config) if config.ready else NullTelegramAdapter()
