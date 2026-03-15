from __future__ import annotations

from app.bot.domain import BotProfile, ClarificationRequest, StoredSource


def format_profile(profile: BotProfile) -> str:
    return (
        "Твой профиль:\n"
        f"- ФИО: {profile.full_name}\n"
        f"- Группа: {profile.group_name}"
    )


def format_source_summary(source: StoredSource) -> str:
    parts = [
        f"Источник #{source.id}",
        f"Статус: {source.status}",
    ]
    if source.subject_name:
        parts.append(f"Предмет: {source.subject_name}")
    if source.overall_confidence is not None:
        parts.append(f"Уверенность: {source.overall_confidence:.2f}")
    if source.progress_message:
        parts.append(f"Статус обработки: {source.progress_message}")
    if source.last_error:
        parts.append(f"Ошибка: {source.last_error}")
    parts.append(f"Ссылка: {source.source_url}")
    return "\n".join(parts)


def format_summary(sources: list[StoredSource]) -> str:
    completed = [source for source in sources if source.normalized]
    if not completed:
        return "Пока нет завершенных анализов. Добавь источник, и я соберу первую сводку."
    subject_lines: list[str] = []
    predicted_scores: list[float] = []
    high_risk_count = 0
    missing_data_sources = 0
    for source in completed:
        normalized = source.normalized or {}
        summary = normalized.get("global_summary", {})
        subjects = normalized.get("subjects", [])
        if summary.get("missing_data_sources"):
            missing_data_sources += int(summary["missing_data_sources"])
        for subject in subjects:
            predicted = float(subject.get("predicted_score", 0.0))
            predicted_scores.append(predicted)
            risk_level = subject.get("risk_level", "unknown")
            if risk_level == "high":
                high_risk_count += 1
            subject_lines.append(
                f"{subject.get('name', 'Без названия')}: прогноз {predicted:.1f}, риск {translate_risk(risk_level)}"
            )
    average_score = sum(predicted_scores) / len(predicted_scores) if predicted_scores else 0.0
    lines = [
        "Сводка по учебе:",
        f"- Средний прогноз: {average_score:.1f}",
        f"- Предметов с высоким риском: {high_risk_count}",
        f"- Неполных источников: {missing_data_sources}",
        "",
    ]
    lines.extend(subject_lines)
    return "\n".join(lines)


def format_subject_details(source: StoredSource) -> str:
    normalized = source.normalized or {}
    subjects = normalized.get("subjects", [])
    if not subjects:
        return "По этому источнику пока нет готового результата."
    subject = subjects[0]
    lines = [
        str(subject.get("name", source.subject_name or "Предмет")),
        f"Текущий балл: {float(subject.get('current_weighted_score', 0.0)):.1f}",
        f"Прогноз: {float(subject.get('predicted_score', 0.0)):.1f}",
        f"Риск: {translate_risk(str(subject.get('risk_level', 'unknown')))}",
        "",
        "Компоненты:",
    ]
    for component in subject.get("components", []):
        score = component.get("score")
        if score is None:
            score_part = "pending"
        else:
            score_part = f"{score}/{component.get('max_score')}"
        lines.append(
            f"- {component.get('name')}: {score_part}, вес {component.get('weight')}"
        )
    warnings = normalized.get("warnings", [])
    if warnings:
        lines.append("")
        lines.append("Предупреждения:")
        for warning in warnings[:3]:
            lines.append(f"- {warning}")
    lines.append("")
    lines.append(f"Источник: {source.source_url}")
    return "\n".join(lines)


def format_deadlines(sources: list[StoredSource]) -> str:
    items: list[tuple[str, str, str]] = []
    for source in sources:
        normalized = source.normalized or {}
        for deadline in normalized.get("deadlines", []):
            items.append(
                (
                    deadline.get("date", ""),
                    deadline.get("urgency", "medium"),
                    f"{deadline.get('subject')} - {deadline.get('name')} - {deadline.get('date')} - {translate_urgency(deadline.get('urgency', 'medium'))}",
                )
            )
    if not items:
        return "Я пока не нашел надежных дедлайнов в загруженных источниках."
    urgency_rank = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda item: (urgency_rank.get(item[1], 9), item[0]))
    return "Ближайшие дедлайны:\n" + "\n".join(f"- {item[2]}" for item in items)


def format_recommendations(sources: list[StoredSource]) -> str:
    lines = ["Рекомендации:"]
    count = 0
    for source in sources:
        normalized = source.normalized or {}
        for recommendation in normalized.get("recommendations", [])[:3]:
            lines.append(
                f"- {recommendation.get('subject')}: {recommendation.get('action')} ({translate_urgency(recommendation.get('urgency', 'medium'))})"
            )
            count += 1
            if count >= 5:
                return "\n".join(lines)
    if count == 0:
        return "Пока нет готовых рекомендаций. Добавь источник или дождись завершения анализа."
    return "\n".join(lines)


def format_clarification(request: ClarificationRequest) -> str:
    lines = [request.prompt]
    if request.hypothesis:
        lines.append(f"Гипотеза: {request.hypothesis}")
    if request.options:
        lines.append("Варианты:")
        for option in request.options:
            lines.append(f"- {option}")
    return "\n".join(lines)


def translate_risk(risk_level: str) -> str:
    mapping = {
        "high": "высокий",
        "medium": "средний",
        "low": "низкий",
    }
    return mapping.get(risk_level, risk_level)


def translate_urgency(urgency: str) -> str:
    mapping = {
        "high": "высокий приоритет",
        "medium": "средний приоритет",
        "low": "низкий приоритет",
    }
    return mapping.get(urgency, urgency)
