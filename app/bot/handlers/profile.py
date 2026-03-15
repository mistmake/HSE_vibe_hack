from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.formatters import format_profile
from app.bot.services.contracts import StudyBotService


def build_profile_router(service: StudyBotService) -> Router:
    router = Router()

    @router.message(Command("profile"))
    async def profile(message: Message) -> None:
        profile_item = service.get_profile(message.from_user.id)
        if profile_item is None:
            await message.answer("Профиль еще не создан. Начни с /start.")
            return
        await message.answer(format_profile(profile_item))

    @router.message(F.text == "/profile")
    async def profile_text(message: Message) -> None:
        profile_item = service.get_profile(message.from_user.id)
        if profile_item is None:
            await message.answer("Профиль еще не создан. Начни с /start.")
            return
        await message.answer(format_profile(profile_item))

    return router
