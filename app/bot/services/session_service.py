from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ChatSession:
    telegram_id: int
    last_source_id: int | None = None


class SessionService:
    def __init__(self) -> None:
        self._sessions: dict[int, ChatSession] = {}

    def get(self, telegram_id: int) -> ChatSession:
        if telegram_id not in self._sessions:
            self._sessions[telegram_id] = ChatSession(telegram_id=telegram_id)
        return self._sessions[telegram_id]

    def set_last_source(self, telegram_id: int, source_id: int) -> None:
        session = self.get(telegram_id)
        session.last_source_id = source_id
