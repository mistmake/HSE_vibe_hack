from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.formatters import format_profile
from app.bot.keyboards import main_menu_keyboard
from app.bot.services.contracts import StudyBotService
from app.bot.services.session_service import SessionService
from app.bot.states import BotStates


def build_start_router(service: StudyBotService, sessions: SessionService) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        telegram_id = message.from_user.id
        profile = service.get_profile(telegram_id)
        if profile is None:
            await state.set_state(BotStates.onboarding_full_name)
            await message.answer(
                "Я помогу собрать учебную сводку по твоим таблицам. Для начала пришли ФИО."
            )
            return
        await state.clear()
        await message.answer(
            format_profile(profile),
            reply_markup=main_menu_keyboard(),
        )

    @router.message(BotStates.onboarding_full_name, F.text)
    async def onboarding_full_name(message: Message, state: FSMContext) -> None:
        await state.update_data(full_name=message.text.strip())
        await state.set_state(BotStates.onboarding_group)
        await message.answer("Теперь пришли группу, например `БПМИ231`.", parse_mode="Markdown")

    @router.message(BotStates.onboarding_group, F.text)
    async def onboarding_group(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        profile = service.register_profile(
            telegram_id=message.from_user.id,
            full_name=data["full_name"],
            group_name=message.text.strip(),
        )
        sessions.get(message.from_user.id)
        await state.clear()
        await message.answer(
            "Профиль сохранен. Теперь пришли публичную ссылку на Google Sheets с ведомостью.",
            reply_markup=main_menu_keyboard(),
        )
        await message.answer(format_profile(profile))

    @router.message(F.text == "Сводка")
    async def menu_summary(message: Message) -> None:
        await message.answer("Открой /summary, и я покажу текущую сводку.")

    @router.message(F.text == "Профиль")
    async def menu_profile(message: Message) -> None:
        profile = service.get_profile(message.from_user.id)
        if profile is None:
            await message.answer("Профиль пока пустой. Нажми /start, и мы его соберем.")
            return
        await message.answer(format_profile(profile))

    @router.message(F.text == "Добавить источник")
    async def menu_add_source(message: Message, state: FSMContext) -> None:
        await state.set_state(BotStates.waiting_source_url)
        await message.answer("Пришли публичную ссылку на Google Sheets.")

    @router.message(F.text == "Источники")
    async def menu_sources(message: Message) -> None:
        await message.answer("Открой /sources, и я покажу все сохраненные источники.")

    @router.message(F.text == "Дедлайны")
    async def menu_deadlines(message: Message) -> None:
        await message.answer("Открой /deadlines, и я покажу ближайшие даты.")

    @router.message(F.text == "Советы")
    async def menu_advice(message: Message) -> None:
        await message.answer("Открой /advice, и я покажу рекомендации.")

    return router
