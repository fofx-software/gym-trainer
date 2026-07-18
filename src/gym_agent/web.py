from __future__ import annotations

from contextlib import asynccontextmanager
import hmac
import logging

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route
from telegram import Update

from .bot import GymBot
from .config import Settings


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> Starlette:
    configured = settings or Settings.from_env()
    if not configured.webhook_secret:
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET is required for the web service")

    telegram = GymBot(configured).application()

    @asynccontextmanager
    async def lifespan(app: Starlette):
        await telegram.initialize()
        await telegram.start()
        if configured.webhook_url:
            await telegram.bot.set_webhook(
                url=f"{configured.webhook_url.rstrip('/')}/telegram",
                allowed_updates=Update.ALL_TYPES,
                secret_token=configured.webhook_secret,
            )
            logger.info("Telegram webhook registered at %s/telegram", configured.webhook_url)
        else:
            logger.warning("WEBHOOK_URL is unset; HTTP server is ready but webhook is not registered")
        yield
        await telegram.stop()
        await telegram.shutdown()

    async def health(request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def telegram_update(request: Request) -> Response:
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(supplied, configured.webhook_secret or ""):
            return PlainTextResponse("unauthorized", status_code=401)
        try:
            update = Update.de_json(await request.json(), telegram.bot)
            await telegram.process_update(update)
        except Exception:
            logger.exception("Telegram webhook processing failed")
            return PlainTextResponse("update failed", status_code=500)
        return PlainTextResponse("ok")

    return Starlette(
        routes=[
            Route("/", health, methods=["GET"]),
            Route("/health", health, methods=["GET"]),
            Route("/telegram", telegram_update, methods=["POST"]),
        ],
        lifespan=lifespan,
    )


app = create_app()


def main() -> None:
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run("gym_agent.web:app", host="0.0.0.0", port=settings.port)
