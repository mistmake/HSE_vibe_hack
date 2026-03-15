from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message


def build_help_router() -> Router:
    router = Router()

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(
            "Команды бота:\n"
            "/start - onboarding\n"
            "/profile - показать профиль\n"
            "/sync - найти и обновить все ведомости по профилю\n"
            "/add_source - добавить Google Sheets вручную (резервный путь)\n"
            "/sources - список источников\n"
            "/summary - сводка\n"
            "/subject - карточка предмета\n"
            "/deadlines - дедлайны\n"
            "/advice - рекомендации"
        )

    return router
