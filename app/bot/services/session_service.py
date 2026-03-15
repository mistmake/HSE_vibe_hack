from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ChatSession:
    telegram_id: int
    last_source_id: int | None = None
    pending_source_matches: list[dict[str, str | None]] = field(default_factory=list)
    selected_source_indexes: set[int] = field(default_factory=set)


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

    def set_pending_source_matches(self, telegram_id: int, matches: list[dict[str, str | None]]) -> None:
        session = self.get(telegram_id)
        session.pending_source_matches = [dict(match) for match in matches]
        session.selected_source_indexes = set()

    def toggle_pending_source(self, telegram_id: int, index: int) -> ChatSession:
        session = self.get(telegram_id)
        if index in session.selected_source_indexes:
            session.selected_source_indexes.remove(index)
        else:
            session.selected_source_indexes.add(index)
        return session

    def selected_pending_source_matches(self, telegram_id: int) -> list[dict[str, str | None]]:
        session = self.get(telegram_id)
        return [
            session.pending_source_matches[index]
            for index in sorted(session.selected_source_indexes)
            if 0 <= index < len(session.pending_source_matches)
        ]

    def clear_pending_source_matches(self, telegram_id: int) -> None:
        session = self.get(telegram_id)
        session.pending_source_matches = []
        session.selected_source_indexes = set()
