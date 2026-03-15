from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import ClarificationCallback, SourceActionCallback, SubjectCallback
from app.bot.domain import ClarificationRequest, StoredSource


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Добавить источник"), KeyboardButton(text="Сводка")],
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
        text="Подробнее",
        callback_data=SubjectCallback(source_id=source.id).pack(),
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
