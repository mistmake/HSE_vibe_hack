from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class BotConfig:
    telegram_token: str
    database_path: Path
    llm_model: str = "gpt-5-mini"
    enable_llm_student_match: bool = False
    enable_llm_structure: bool = True

    @classmethod
    def from_env(cls) -> "BotConfig":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        db_path = Path(os.getenv("BOT_DB_PATH", "bot_storage.sqlite3")).resolve()
        return cls(
            telegram_token=token,
            database_path=db_path,
            llm_model=os.getenv("STUDY_ANALYSIS_LLM_MODEL", "gpt-5-mini"),
            enable_llm_student_match=os.getenv("BOT_ENABLE_LLM_STUDENT_MATCH", "0") == "1",
            enable_llm_structure=os.getenv("BOT_ENABLE_LLM_STRUCTURE", "1") == "1",
        )
