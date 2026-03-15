from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.formatters import format_deadlines
from app.bot.services.contracts import StudyBotService


def build_deadlines_router(service: StudyBotService) -> Router:
    router = Router()

    @router.message(Command("deadlines"))
    async def deadlines(message: Message) -> None:
        await message.answer(format_deadlines(service.completed_sources(message.from_user.id)))

    return router
