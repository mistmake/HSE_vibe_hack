from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import SubjectCallback
from app.bot.formatters import format_subject_details
from app.bot.keyboards import source_actions_keyboard
from app.bot.services.contracts import StudyBotService
from app.bot.services.session_service import SessionService


def build_subject_router(service: StudyBotService, sessions: SessionService) -> Router:
    router = Router()

    @router.message(Command("subject"))
    async def subject(message: Message) -> None:
        completed_sources = service.completed_sources(message.from_user.id)
        if not completed_sources:
            await message.answer("Пока нет завершенных анализов, чтобы показать предмет.")
            return
        session = sessions.get(message.from_user.id)
        if session.last_source_id is not None:
            source = service.get_source(message.from_user.id, session.last_source_id)
            if source is not None and source.normalized:
                await message.answer(format_subject_details(source))
                return
        for source in completed_sources:
            await message.answer(
                f"{source.subject_name or 'Предмет'}",
                reply_markup=source_actions_keyboard(source),
            )

    @router.callback_query(SubjectCallback.filter())
    async def subject_callback(callback: CallbackQuery, callback_data: SubjectCallback) -> None:
        source = service.get_source(callback.from_user.id, callback_data.source_id)
        if source is None:
            await callback.answer("Предмет не найден.", show_alert=True)
            return
        await callback.answer()
        await callback.message.answer(format_subject_details(source))

    return router
