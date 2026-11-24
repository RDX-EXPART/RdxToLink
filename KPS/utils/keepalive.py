# KPS/utils/keepalive.py

import asyncio
import aiohttp
from KPS.vars import Var
from KPS.utils.logger import logger

async def ping_server():
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            while True:
                try:
                    await asyncio.sleep(Var.PING_INTERVAL)
                    target = Var.URL.rstrip("/") + "/status"
                    async with session.get(target) as resp:
                        if resp.status != 200:
                            logger.warning(f"Ping to {target} returned status {resp.status}.")
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.warning(f"Keep-alive ping error (will retry): {exc}")
    except Exception as e:
        logger.error(f"Error in ping_server: {e}", exc_info=True)
