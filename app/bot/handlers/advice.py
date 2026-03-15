from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.formatters import format_recommendations
from app.bot.services.contracts import StudyBotService


def build_advice_router(service: StudyBotService) -> Router:
    router = Router()

    @router.message(Command("advice"))
    async def advice(message: Message) -> None:
        await message.answer(format_recommendations(service.completed_sources(message.from_user.id)))

    return router
