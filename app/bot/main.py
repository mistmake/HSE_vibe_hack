from __future__ import annotations

import asyncio
import logging

from app.bot.config import BotConfig
from app.bot.handlers import register_routers
from app.bot.services.local_service import LocalStudyBotService
from app.bot.services.local_storage import ProfileRepository, SQLiteStorage, SourceRepository
from app.bot.services.session_service import SessionService


def create_service(config: BotConfig) -> LocalStudyBotService:
    storage = SQLiteStorage(config.database_path)
    return LocalStudyBotService(
        profiles=ProfileRepository(storage),
        sources=SourceRepository(storage),
        llm_model=config.llm_model,
        enable_llm_student_match=config.enable_llm_student_match,
        enable_llm_structure=config.enable_llm_structure,
    )


async def run_polling() -> None:
    try:
        from aiogram import Bot, Dispatcher
    except ImportError as exc:
        raise RuntimeError("Install aiogram to run the Telegram bot.") from exc

    config = BotConfig.from_env()
    if not config.telegram_token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN in the environment before запуском бота.")
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=config.telegram_token)
    dispatcher = Dispatcher()
    service = create_service(config)
    sessions = SessionService()
    register_routers(dispatcher, service=service, sessions=sessions)
    await dispatcher.start_polling(bot)


def main() -> None:
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
