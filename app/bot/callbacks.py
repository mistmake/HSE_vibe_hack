from aiogram.filters.callback_data import CallbackData


class SourceActionCallback(CallbackData, prefix="source"):
    action: str
    source_id: int


class SubjectCallback(CallbackData, prefix="subject"):
    source_id: int


class ClarificationCallback(CallbackData, prefix="clarify"):
    action: str
    source_id: int
