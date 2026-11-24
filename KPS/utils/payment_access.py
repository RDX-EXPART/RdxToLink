# KPS/utils/payment_access.py

from __future__ import annotations

import asyncio
import socket
import time
from typing import Any, Dict, Tuple

import aiohttp
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from KPS.utils.logger import logger
from KPS.vars import Var

_ACCESS_CACHE: Dict[int, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 30.0
_CACHE_MAX_ENTRIES = 2000


def is_payment_enabled() -> bool:
    return bool(
        getattr(Var, "PAYMENT_API_URL", "")
        and getattr(Var, "PAYMENT_API_KEY", "")
        and getattr(Var, "PAYMENT_BOT_USERNAME", "")
    )


def _prune_cache(now: float) -> None:
    if len(_ACCESS_CACHE) <= _CACHE_MAX_ENTRIES:
        return
    expired = [uid for uid, (exp, _) in _ACCESS_CACHE.items() if exp <= now]
    for uid in expired:
        _ACCESS_CACHE.pop(uid, None)
    if len(_ACCESS_CACHE) > _CACHE_MAX_ENTRIES:
        _ACCESS_CACHE.clear()


async def check_central_access(user_id: int) -> Dict[str, Any]:
    """Check whether user_id has active Premium, Verified, or Open access on RDX-Payment-Verify."""
    if not is_payment_enabled():
        return {"allowed": True, "mode": "disabled", "expires_at": None}

    now = time.monotonic()
    cached = _ACCESS_CACHE.get(user_id)
    if cached and cached[0] > now:
        return cached[1]

    url = f"{Var.PAYMENT_API_URL}/api/v1/access/check"
    headers = {"X-API-Key": Var.PAYMENT_API_KEY}
    payload = {"user_id": int(user_id), "service_id": Var.PAYMENT_SERVICE_ID}

    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = {
                        "allowed": bool(data.get("allowed")),
                        "mode": str(data.get("mode") or "none"),
                        "expires_at": data.get("expires_at"),
                    }
                    if result["allowed"]:
                        _prune_cache(now)
                        _ACCESS_CACHE[user_id] = (now + _CACHE_TTL_SECONDS, result)
                    return result
                logger.warning(
                    "Central payment access check returned HTTP %s for user %s",
                    resp.status,
                    user_id,
                )
    except Exception as exc:
        logger.warning("Central payment access check failed for user %s: %s", user_id, exc)

    if getattr(Var, "PAYMENT_FAIL_OPEN", False):
        return {"allowed": True, "mode": "fail_open", "expires_at": None}
    return {"allowed": False, "mode": "error", "expires_at": None}


def build_access_prompt() -> Tuple[str, InlineKeyboardMarkup]:
    bot_user = Var.PAYMENT_BOT_USERNAME.lstrip("@")
    service_id = Var.PAYMENT_SERVICE_ID
    service_name = Var.PAYMENT_SERVICE_NAME
    verify_url = f"https://t.me/{bot_user}?start=service_{service_id}"
    buy_url = f"https://t.me/{bot_user}?start=buy_{service_id}"

    text = (
        f"🔐 <b>Verification Required — {service_name}</b>\n\n"
        "To generate direct download &amp; stream links, please complete a quick "
        "<b>Free Verification</b> or unlock <b>Premium</b> (zero verification).\n\n"
        "• ✅ <b>Free Verify:</b> Quick 1-step verification\n"
        "• ⭐ <b>Premium:</b> Telegram Stars, USDT, Binance Pay (0% Fee), TON, or Voucher Key"
    )
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔐 Free Verify Now", url=verify_url)],
            [InlineKeyboardButton("⭐ Buy Premium (No Verify)", url=buy_url)],
        ]
    )
    return text, markup


async def send_heartbeat_once(bot_username: str) -> bool:
    if not is_payment_enabled():
        return False
    url = f"{Var.PAYMENT_API_URL}/api/v1/services/heartbeat"
    headers = {"X-API-Key": Var.PAYMENT_API_KEY}
    payload = {
        "service_id": Var.PAYMENT_SERVICE_ID,
        "bot_username": (bot_username or "").lstrip("@"),
        "instance_id": socket.gethostname()[:128],
    }
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    return True
                logger.warning("Central heartbeat returned HTTP %s", resp.status)
    except Exception as exc:
        logger.warning("Central heartbeat error: %s", exc)
    return False


async def heartbeat_loop(bot_username: str) -> None:
    if not is_payment_enabled():
        return
    interval = max(30, int(getattr(Var, "PAYMENT_HEARTBEAT_SECONDS", 60)))
    logger.info(
        "Starting central payment heartbeat loop for service '%s' every %ss.",
        Var.PAYMENT_SERVICE_ID,
        interval,
    )
    while True:
        try:
            await send_heartbeat_once(bot_username)
        except asyncio.CancelledError:
            logger.debug("Payment heartbeat loop cancelled cleanly.")
            break
        except Exception as exc:
            logger.warning("Unexpected error in payment heartbeat loop: %s", exc)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
