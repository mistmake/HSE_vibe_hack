from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BotProfile:
    telegram_id: int
    full_name: str
    group_name: str
    program_code: str | None
    created_at: str
    updated_at: str


@dataclass(slots=True)
class ClarificationRequest:
    kind: str
    prompt: str
    hypothesis: str | None = None
    options: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    response: str | None = None


@dataclass(slots=True)
class ManualFormulaOverride:
    formula_text: str
    weights: dict[str, float] = field(default_factory=dict)
    parser_confidence: float = 0.0
    source_type: str = "text"
    reason: str | None = None


@dataclass(slots=True)
class StoredSource:
    id: int
    telegram_id: int
    source_url: str
    source_type: str
    source_metadata: dict[str, Any]
    status: str
    subject_name: str | None
    overall_confidence: float | None
    progress_message: str | None
    last_error: str | None
    analysis_result: dict[str, Any] | None
    clarification: ClarificationRequest | None
    manual_formula: ManualFormulaOverride | None
    created_at: str
    updated_at: str

    @property
    def normalized(self) -> dict[str, Any] | None:
        if not self.analysis_result:
            return None
        return self.analysis_result.get("normalized")
