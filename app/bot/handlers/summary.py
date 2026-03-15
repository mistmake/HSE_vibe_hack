from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.formatters import format_summary
from app.bot.services.contracts import StudyBotService


def build_summary_router(service: StudyBotService) -> Router:
    router = Router()

    @router.message(Command("summary"))
    async def summary(message: Message) -> None:
        await message.answer(format_summary(service.completed_sources(message.from_user.id)))

    return router
