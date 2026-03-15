from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import ProgramCallback
from app.bot.formatters import format_profile
from app.bot.handlers.sources import prompt_source_selection
from app.bot.keyboards import main_menu_keyboard, program_keyboard
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
            await state.set_state(BotStates.onboarding_program)
            await message.answer(
                "Я помогу собрать учебную сводку по ведомостям. Для начала выбери программу.",
                reply_markup=program_keyboard(),
            )
            return
        await state.clear()
        await message.answer(
            format_profile(profile),
            reply_markup=main_menu_keyboard(),
        )

    @router.callback_query(BotStates.onboarding_program, ProgramCallback.filter())
    async def onboarding_program(
        callback: CallbackQuery,
        callback_data: ProgramCallback,
        state: FSMContext,
    ) -> None:
        await callback.answer("Сохраняю профиль...")
        await state.update_data(program_code=callback_data.code)
        await state.set_state(BotStates.onboarding_group)
        await callback.message.answer(
            "Теперь пришли группу, например `БПАД 257-1`, `257-1`, `БПМИ256` или `256`.",
            parse_mode="Markdown",
        )

    @router.message(BotStates.onboarding_group, F.text)
    async def onboarding_group(message: Message, state: FSMContext) -> None:
        await state.update_data(group_name=message.text.strip())
        await state.set_state(BotStates.onboarding_full_name)
        await message.answer("Теперь пришли ФИО полностью.")

    @router.message(BotStates.onboarding_full_name, F.text)
    async def onboarding_full_name(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        profile = service.register_profile(
            telegram_id=message.from_user.id,
            full_name=message.text.strip(),
            group_name=data["group_name"],
            program_code=data["program_code"],
        )
        sessions.get(message.from_user.id)
        await state.clear()
        await message.answer(
            "Профиль сохранен. Ищу ведомости по группе и программе, это может занять немного времени.",
            reply_markup=main_menu_keyboard(),
        )
        await message.answer(format_profile(profile))
        await prompt_source_selection(
            message,
            service,
            sessions,
            intro_text="Подбираю ведомости по профилю.",
        )

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
