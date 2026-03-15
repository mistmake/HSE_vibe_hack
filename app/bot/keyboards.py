from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import (
    ClarificationCallback,
    ProgramCallback,
    SourceActionCallback,
    SourceSelectionCallback,
    SubjectCallback,
)
from app.bot.domain import ClarificationRequest, StoredSource


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Обновить ведомости"), KeyboardButton(text="Сводка")],
            [KeyboardButton(text="Дедлайны"), KeyboardButton(text="Советы")],
            [KeyboardButton(text="Профиль"), KeyboardButton(text="Источники")],
        ],
        resize_keyboard=True,
    )


def source_actions_keyboard(source: StoredSource) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Запустить анализ" if source.status in {"created", "failed"} else "Переанализировать",
        callback_data=SourceActionCallback(action="analyze", source_id=source.id).pack(),
    )
    builder.button(
        text="Загрузить формулу",
        callback_data=SourceActionCallback(action="formula", source_id=source.id).pack(),
    )
    builder.button(
        text="Подробнее",
        callback_data=SubjectCallback(source_id=source.id).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def discovered_sources_keyboard(
    matches: list[dict[str, str | None]],
    selected_indexes: set[int],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, match in enumerate(matches):
        prefix = "[x]" if index in selected_indexes else "[ ]"
        label = match.get("subject_name") or f"Источник {index + 1}"
        builder.button(
            text=f"{prefix} {label}",
            callback_data=SourceSelectionCallback(action="toggle", index=index).pack(),
        )
    builder.button(
        text="Сохранить выбранные",
        callback_data=SourceSelectionCallback(action="confirm", index=0).pack(),
    )
    builder.button(
        text="Отмена",
        callback_data=SourceSelectionCallback(action="cancel", index=0).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def sources_menu_keyboard(sources: list[StoredSource]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for source in sources:
        title = source.subject_name or f"Источник #{source.id}"
        builder.button(
            text=f"{title} [{source.status}]",
            callback_data=SourceActionCallback(action="open", source_id=source.id).pack(),
        )
    builder.adjust(1)
    return builder.as_markup()


def clarification_keyboard(source_id: int, request: ClarificationRequest) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if request.kind == "student_match":
        builder.button(
            text="Да, это я",
            callback_data=ClarificationCallback(action="confirm", source_id=source_id).pack(),
        )
        builder.button(
            text="Нет",
            callback_data=ClarificationCallback(action="reject", source_id=source_id).pack(),
        )
    else:
        builder.button(
            text="Подтвердить",
            callback_data=ClarificationCallback(action="confirm", source_id=source_id).pack(),
        )
        builder.button(
            text="Пропустить",
            callback_data=ClarificationCallback(action="skip", source_id=source_id).pack(),
        )
    builder.adjust(1)
    return builder.as_markup()


def program_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, label in (
        ("PMI", "ПМИ"),
        ("PI", "ПИ"),
        ("PAD", "ПАД"),
        ("KNAD", "КНАД"),
        ("EAD", "ЭАД"),
        ("DRIP", "ДРИП"),
    ):
        builder.button(
            text=label,
            callback_data=ProgramCallback(code=code).pack(),
        )
    builder.adjust(2)
    return builder.as_markup()
