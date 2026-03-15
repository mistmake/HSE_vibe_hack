from __future__ import annotations

import asyncio
import io

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import ClarificationCallback, SourceActionCallback, SourceSelectionCallback
from app.bot.formatters import (
    format_clarification,
    format_source_summary,
    format_subject_details,
)
from app.bot.keyboards import (
    clarification_keyboard,
    discovered_sources_keyboard,
    source_actions_keyboard,
    sources_menu_keyboard,
)
from app.bot.services.contracts import StudyBotService
from app.bot.services.session_service import SessionService
from app.bot.states import BotStates


async def prompt_source_selection(
    message: Message,
    service: StudyBotService,
    sessions: SessionService,
    *,
    intro_text: str,
) -> None:
    await message.answer(intro_text)
    try:
        matches = await asyncio.to_thread(service.discover_profile_sources, message.from_user.id)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    sessions.set_pending_source_matches(message.from_user.id, matches)
    await message.answer(
        (
            f"Нашел {len(matches)} источников. Отметь нужные предметы и нажми "
            "`Сохранить выбранные`."
        ),
        parse_mode="Markdown",
        reply_markup=discovered_sources_keyboard(matches, set()),
    )


def build_sources_router(service: StudyBotService, sessions: SessionService) -> Router:
    router = Router()

    async def run_profile_sync(message: Message) -> None:
        await prompt_source_selection(
            message,
            service,
            sessions,
            intro_text="Ищу ведомости по профилю.",
        )

    @router.message(Command("add_source"))
    async def add_source_command(message: Message, state: FSMContext) -> None:
        await state.set_state(BotStates.waiting_source_url)
        await message.answer("Пришли публичную ссылку на Google Sheets. Это резервный ручной режим.")

    @router.message(Command("formula"))
    async def formula_command(message: Message, state: FSMContext) -> None:
        session = sessions.get(message.from_user.id)
        if session.last_source_id is None:
            await message.answer("Сначала выбери источник через /sources или запусти анализ, чтобы я понял, куда применять формулу.")
            return
        await state.set_state(BotStates.waiting_formula_input)
        await state.update_data(formula_source_id=session.last_source_id)
        await message.answer("Пришли формулу оценивания текстом или картинкой, и я попробую применить ее к последнему источнику.")

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
        await message.answer(
            "Выбери источник, и я покажу действия по нему.",
            reply_markup=sources_menu_keyboard(sources),
        )

    @router.callback_query(SourceSelectionCallback.filter(F.action == "toggle"))
    async def toggle_discovered_source(
        callback: CallbackQuery,
        callback_data: SourceSelectionCallback,
    ) -> None:
        session = sessions.get(callback.from_user.id)
        if not session.pending_source_matches:
            await callback.answer("Меню выбора устарело. Запусти /sync заново.", show_alert=True)
            return
        if callback_data.index < 0 or callback_data.index >= len(session.pending_source_matches):
            await callback.answer("Не нашел этот вариант.", show_alert=True)
            return
        session = sessions.toggle_pending_source(callback.from_user.id, callback_data.index)
        await callback.answer("Выбор обновлен.")
        await callback.message.edit_reply_markup(
            reply_markup=discovered_sources_keyboard(
                session.pending_source_matches,
                session.selected_source_indexes,
            )
        )

    @router.callback_query(SourceSelectionCallback.filter(F.action == "confirm"))
    async def confirm_discovered_sources(
        callback: CallbackQuery,
        callback_data: SourceSelectionCallback,
    ) -> None:
        del callback_data
        session = sessions.get(callback.from_user.id)
        selected_matches = sessions.selected_pending_source_matches(callback.from_user.id)
        if not session.pending_source_matches:
            await callback.answer("Меню выбора устарело. Запусти /sync заново.", show_alert=True)
            return
        if not selected_matches:
            await callback.answer("Сначала отметь хотя бы один источник.", show_alert=True)
            return
        stored_sources = await asyncio.to_thread(
            service.save_discovered_sources,
            callback.from_user.id,
            selected_matches,
        )
        sessions.clear_pending_source_matches(callback.from_user.id)
        if callback.message is not None:
            await callback.message.edit_text(
                "Сохранил выбранные источники."
            )
            if stored_sources:
                sessions.set_last_source(callback.from_user.id, stored_sources[0].id)
            await callback.message.answer(
                "Теперь выбери источник, и я покажу доступные действия.",
                reply_markup=sources_menu_keyboard(stored_sources),
            )
        await callback.answer("Источники сохранены.")

    @router.callback_query(SourceSelectionCallback.filter(F.action == "cancel"))
    async def cancel_discovered_sources(
        callback: CallbackQuery,
        callback_data: SourceSelectionCallback,
    ) -> None:
        del callback_data
        sessions.clear_pending_source_matches(callback.from_user.id)
        await callback.answer("Выбор отменен.")
        if callback.message is not None:
            await callback.message.edit_text("Выбор источников отменен. Если захочешь, запусти /sync снова.")

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

    @router.callback_query(SourceActionCallback.filter(F.action == "open"))
    async def open_source(callback: CallbackQuery, callback_data: SourceActionCallback) -> None:
        source = service.get_source(callback.from_user.id, callback_data.source_id)
        if source is None:
            await callback.answer("Источник не найден.", show_alert=True)
            return
        sessions.set_last_source(callback.from_user.id, source.id)
        await callback.answer()
        await callback.message.answer(
            format_source_summary(source),
            reply_markup=source_actions_keyboard(source),
        )

    @router.callback_query(SourceActionCallback.filter(F.action == "formula"))
    async def request_formula(callback: CallbackQuery, callback_data: SourceActionCallback, state: FSMContext) -> None:
        await callback.answer("Жду формулу...")
        sessions.set_last_source(callback.from_user.id, callback_data.source_id)
        await state.set_state(BotStates.waiting_formula_input)
        await state.update_data(formula_source_id=callback_data.source_id)
        await callback.message.answer("Пришли формулу оценивания текстом или картинкой, и я обновлю веса.")

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

    @router.message(BotStates.waiting_formula_input, F.text)
    async def receive_formula_text(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        source_id = data.get("formula_source_id")
        if source_id is None:
            await state.clear()
            await message.answer("Не понял, к какому источнику применять формулу. Выбери предмет заново через /sources.")
            return
        await message.answer("Разбираю формулу и пересчитываю веса.")
        try:
            source = await asyncio.to_thread(
                service.apply_manual_formula_text,
                message.from_user.id,
                int(source_id),
                message.text,
            )
        except Exception as exc:
            await message.answer(str(exc))
            return
        sessions.set_last_source(message.from_user.id, source.id)
        await state.clear()
        await message.answer(format_subject_details(source))

    @router.message(BotStates.waiting_formula_input, F.photo)
    async def receive_formula_photo(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        source_id = data.get("formula_source_id")
        if source_id is None:
            await state.clear()
            await message.answer("Не понял, к какому источнику применять формулу. Выбери предмет заново через /sources.")
            return
        buffer = io.BytesIO()
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        await message.bot.download_file(file.file_path, destination=buffer)
        await message.answer("Читаю формулу с картинки и пересчитываю веса.")
        try:
            source = await asyncio.to_thread(
                service.apply_manual_formula_image,
                message.from_user.id,
                int(source_id),
                buffer.getvalue(),
                "image/jpeg",
            )
        except Exception as exc:
            await message.answer(str(exc))
            return
        sessions.set_last_source(message.from_user.id, source.id)
        await state.clear()
        await message.answer(format_subject_details(source))

    @router.message(BotStates.waiting_formula_input, F.document)
    async def receive_formula_document(message: Message, state: FSMContext) -> None:
        if message.document is None or not (message.document.mime_type or "").startswith("image/"):
            await message.answer("Для формулы как файла пришли именно изображение или просто отправь текст формулы.")
            return
        data = await state.get_data()
        source_id = data.get("formula_source_id")
        if source_id is None:
            await state.clear()
            await message.answer("Не понял, к какому источнику применять формулу. Выбери предмет заново через /sources.")
            return
        buffer = io.BytesIO()
        file = await message.bot.get_file(message.document.file_id)
        await message.bot.download_file(file.file_path, destination=buffer)
        await message.answer("Читаю формулу с картинки и пересчитываю веса.")
        try:
            source = await asyncio.to_thread(
                service.apply_manual_formula_image,
                message.from_user.id,
                int(source_id),
                buffer.getvalue(),
                message.document.mime_type or "image/jpeg",
            )
        except Exception as exc:
            await message.answer(str(exc))
            return
        sessions.set_last_source(message.from_user.id, source.id)
        await state.clear()
        await message.answer(format_subject_details(source))

    return router
