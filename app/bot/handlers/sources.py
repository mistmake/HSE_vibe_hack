from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import ClarificationCallback, SourceActionCallback
from app.bot.formatters import (
    format_clarification,
    format_source_summary,
    format_subject_details,
    format_summary,
    format_sync_report,
)
from app.bot.keyboards import clarification_keyboard, source_actions_keyboard
from app.bot.services.contracts import StudyBotService
from app.bot.services.session_service import SessionService
from app.bot.states import BotStates


def build_sources_router(service: StudyBotService, sessions: SessionService) -> Router:
    router = Router()

    async def run_profile_sync(message: Message) -> None:
        await message.answer("Ищу ведомости по профилю и запускаю анализ.")
        try:
            sources = await asyncio.to_thread(service.sync_and_analyze_profile, message.from_user.id)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        for source in sources:
            sessions.set_last_source(message.from_user.id, source.id)
        await message.answer(format_sync_report(sources))
        await message.answer(format_summary(sources))
        next_source = next(
            (
                source
                for source in sources
                if source.status == "needs_clarification" and source.clarification is not None
            ),
            None,
        )
        if next_source is not None and next_source.clarification is not None:
            await message.answer(
                format_clarification(next_source.clarification),
                reply_markup=clarification_keyboard(next_source.id, next_source.clarification),
            )

    @router.message(Command("add_source"))
    async def add_source_command(message: Message, state: FSMContext) -> None:
        await state.set_state(BotStates.waiting_source_url)
        await message.answer("Пришли публичную ссылку на Google Sheets. Это резервный ручной режим.")

    @router.message(Command("sync"))
    async def sync_command(message: Message) -> None:
        await run_profile_sync(message)

    @router.message(F.text == "Обновить ведомости")
    async def sync_menu(message: Message) -> None:
        await run_profile_sync(message)

    @router.message(Command("sources"))
    async def list_sources(message: Message) -> None:
        sources = service.list_sources(message.from_user.id)
        if not sources:
            await message.answer("Пока нет сохраненных источников. Запусти /sync, и я найду их по профилю.")
            return
        for source in sources:
            await message.answer(
                format_source_summary(source),
                reply_markup=source_actions_keyboard(source),
            )

    @router.message(BotStates.waiting_source_url, F.text)
    async def receive_source(message: Message, state: FSMContext) -> None:
        try:
            source = service.add_source(message.from_user.id, message.text)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        sessions.set_last_source(message.from_user.id, source.id)
        await state.clear()
        await message.answer(
            "Источник сохранен. Теперь можно запускать анализ.",
            reply_markup=source_actions_keyboard(source),
        )

    @router.callback_query(SourceActionCallback.filter(F.action == "analyze"))
    async def analyze_source(callback: CallbackQuery, callback_data: SourceActionCallback) -> None:
        await callback.answer("Запускаю анализ...")
        source = await asyncio.to_thread(
            service.run_analysis,
            callback.from_user.id,
            callback_data.source_id,
        )
        sessions.set_last_source(callback.from_user.id, source.id)
        if source.status == "needs_clarification" and source.clarification is not None:
            await callback.message.answer(
                format_clarification(source.clarification),
                reply_markup=clarification_keyboard(source.id, source.clarification),
            )
            return
        if source.status == "completed":
            await callback.message.answer(format_subject_details(source))
            return
        await callback.message.answer(format_source_summary(source))

    @router.callback_query(ClarificationCallback.filter())
    async def clarification_response(
        callback: CallbackQuery,
        callback_data: ClarificationCallback,
    ) -> None:
        await callback.answer("Сохраняю ответ...")
        source = service.resolve_clarification(
            callback.from_user.id,
            callback_data.source_id,
            callback_data.action,
        )
        await callback.message.answer(format_subject_details(source))
        next_source = next(
            (
                item
                for item in service.list_sources(callback.from_user.id)
                if item.id != source.id and item.status == "needs_clarification" and item.clarification is not None
            ),
            None,
        )
        if next_source is not None and next_source.clarification is not None:
            await callback.message.answer(
                format_clarification(next_source.clarification),
                reply_markup=clarification_keyboard(next_source.id, next_source.clarification),
            )

    return router
