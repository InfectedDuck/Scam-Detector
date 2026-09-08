"""Entrypoint. Long polling, one process, no inbound port.

Long polling rather than webhooks, per the architecture: it removes the need for
inbound TLS on the bot container and it behaves identically on a laptop and on
the Hetzner box, so the demo path and the development path are the same path.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeDefault

from saqbol.bot.config import BotConfig
from saqbol.bot.deps import Deps, build_deps
from saqbol.bot.handlers import build_router
from saqbol.bot.strings import FALLBACK_LOCALE, SUPPORTED_LOCALES, t
from saqbol.core.types import Lang

log = logging.getLogger(__name__)

COMMANDS = ("start", "help", "privacy", "forget")


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging, and keep third-party DEBUG from leaking identifiers.

    `handlers.py` is careful never to log a raw Telegram id, but aiogram's own
    debug logging prints update payloads, which contain them. So the aiogram
    loggers are clamped to INFO even when the application is turned up to DEBUG.
    Turning them down is a deliberate act, not something a stray `-v` does.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )
    logging.getLogger("aiogram").setLevel(max(level, logging.INFO))


def build_dispatcher(deps: Deps) -> Dispatcher:
    """A dispatcher with `deps` in workflow data, which is how handlers get it."""
    dispatcher = Dispatcher(deps=deps)
    dispatcher.include_router(build_router())
    return dispatcher


def command_menu(locale: Lang) -> list[BotCommand]:
    return [BotCommand(command=name, description=t(locale, f"cmd_{name}")) for name in COMMANDS]


async def publish_commands(bot: Bot) -> None:
    """Register the command menu, once per supported language."""
    await bot.set_my_commands(command_menu(FALLBACK_LOCALE), scope=BotCommandScopeDefault())
    for locale in SUPPORTED_LOCALES:
        if locale is FALLBACK_LOCALE:
            continue
        await bot.set_my_commands(
            command_menu(locale),
            scope=BotCommandScopeDefault(),
            language_code=locale.value,
        )


async def run(config: BotConfig | None = None) -> None:
    config = config or BotConfig.from_env()
    if not config.token:
        msg = "TELEGRAM_BOT_TOKEN is not set"
        raise RuntimeError(msg)

    deps = build_deps(config)
    if deps.analyze_is_stub or deps.renderer_is_stub:
        log.warning(
            "starting with stubs (analyze=%s, renderer=%s); verdicts are fixtures",
            deps.analyze_is_stub,
            deps.renderer_is_stub,
        )

    bot = Bot(config.token)
    dispatcher = build_dispatcher(deps)
    await publish_commands(bot)
    log.info("polling, limit=%d/day, state=%s", config.daily_check_limit, config.state_path)
    await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())


def main() -> None:
    setup_logging()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
