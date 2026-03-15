from __future__ import annotations

from typing import Protocol

from app.bot.domain import BotProfile, StoredSource


class StudyBotService(Protocol):
    def get_profile(self, telegram_id: int) -> BotProfile | None:
        ...

    def register_profile(
        self,
        telegram_id: int,
        full_name: str,
        group_name: str,
        program_code: str | None = None,
    ) -> BotProfile:
        ...

    def add_source(self, telegram_id: int, source_url: str) -> StoredSource:
        ...

    def discover_profile_sources(self, telegram_id: int) -> list[dict[str, str | None]]:
        ...

    def save_discovered_sources(
        self,
        telegram_id: int,
        matches: list[dict[str, str | None]],
    ) -> list[StoredSource]:
        ...

    def sync_profile_sources(self, telegram_id: int) -> list[StoredSource]:
        ...

    def sync_and_analyze_profile(self, telegram_id: int) -> list[StoredSource]:
        ...

    def list_sources(self, telegram_id: int) -> list[StoredSource]:
        ...

    def completed_sources(self, telegram_id: int) -> list[StoredSource]:
        ...

    def get_source(self, telegram_id: int, source_id: int) -> StoredSource | None:
        ...

    def run_analysis(self, telegram_id: int, source_id: int) -> StoredSource:
        ...

    def apply_manual_formula_text(self, telegram_id: int, source_id: int, formula_text: str) -> StoredSource:
        ...

    def apply_manual_formula_image(
        self,
        telegram_id: int,
        source_id: int,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> StoredSource:
        ...

    def resolve_clarification(self, telegram_id: int, source_id: int, action: str) -> StoredSource:
        ...
