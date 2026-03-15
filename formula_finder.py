from __future__ import annotations

import argparse
import html
import json
import re
from difflib import SequenceMatcher

from gradebook_finder import (
    DEFAULT_ACADEMIC_YEAR,
    WIKI_HUB_TITLE,
    extract_program_section,
    extract_subject_pages,
    fetch_wiki_raw,
    normalize_program_code,
    normalize_subject_key,
    wiki_page_url,
    PROGRAM_SECTION_IDS,
)
from openai_json_client import call_openai_json, has_openai_api_key


def parse_module_number(module_value: str | int | None) -> int | None:
    if module_value is None:
        return None
    if isinstance(module_value, int):
        return module_value

    match = re.search(r"\d+", str(module_value))
    return int(match.group()) if match else None


def clean_formula_line(line: str) -> str:
    cleaned = line.replace("'''", "")
    cleaned = re.sub(r"<sub>\s*([^<]+)\s*</sub>", r"\1", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<br\s*/?>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"\[([^\s\]]+)\s+([^\]]+)\]", r"\2", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def locate_subject_page(subject_name: str, program_code: str) -> dict:
    resolved_program = normalize_program_code(program_code, program_code)
    section_id = PROGRAM_SECTION_IDS.get(resolved_program)
    if not section_id:
        raise ValueError(f"Для программы {resolved_program} пока нет секции на wiki.")

    hub_raw = fetch_wiki_raw(WIKI_HUB_TITLE)
    section_raw = extract_program_section(hub_raw, section_id)
    subject_pages = extract_subject_pages(section_raw)
    if not subject_pages:
        raise ValueError(f"Для программы {resolved_program} не найдены страницы предметов на wiki.")

    lookup = normalize_subject_key(subject_name)
    exact_matches = []
    partial_matches = []
    scored_matches = []

    for page in subject_pages:
        candidates = [
            normalize_subject_key(page["label"]),
            normalize_subject_key(page["title"]),
        ]

        if lookup in candidates:
            exact_matches.append(page)
            continue

        if any(lookup and (lookup in candidate or candidate in lookup) for candidate in candidates):
            partial_matches.append(page)
            continue

        score = max(SequenceMatcher(None, lookup, candidate).ratio() for candidate in candidates)
        scored_matches.append((score, page))

    if exact_matches:
        return exact_matches[0]
    if partial_matches:
        partial_matches.sort(key=lambda page: len(page["label"]))
        return partial_matches[0]

    scored_matches.sort(key=lambda item: item[0], reverse=True)
    best_score, best_page = scored_matches[0]
    if best_score < 0.45:
        raise ValueError(f"Не удалось сопоставить предмет '{subject_name}' со страницей wiki для программы {resolved_program}.")

    return best_page


def extract_formula_section(raw_text: str) -> str:
    lines = raw_text.splitlines()
    preferred_markers = ("grading system", "grading", "formula", "grades")

    for marker in preferred_markers:
        collected: list[str] = []
        capture = False

        for line in lines:
            stripped = line.strip()
            is_heading = bool(re.match(r"^=+.*=+$", stripped))
            heading_key = normalize_subject_key(stripped)

            if is_heading and marker in heading_key:
                capture = True
                collected.append(line)
                continue

            if capture and is_heading:
                break

            if capture:
                collected.append(line)

        if collected:
            return "\n".join(collected)[:12000]

    relevant = []
    for line in lines:
        lowered = line.lower()
        if any(marker in lowered for marker in ("cum", "exam", "final", "grade", "formula", "=")):
            relevant.append(line)

    if relevant:
        return "\n".join(relevant)[:12000]

    return raw_text[:12000]


def fallback_formula_lines(raw_text: str, module_number: int | None) -> list[str]:
    relevant_text = extract_formula_section(raw_text)
    lines = []
    for raw_line in relevant_text.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue

        lowered = line.lower()
        if any(marker in lowered for marker in ("classroom", "telegram", "google.com", "links", "tg:")):
            continue

        compact = re.sub(r"\s+", "", line).upper()
        if module_number in (1, 2) and any(token in compact for token in ("CUM<SUB>1</SUB>", "G<SUB>1</SUB>", "CUM1", "G1", "FINAL<SUB>1</SUB>", "M1")):
            lines.append(clean_formula_line(line))
        elif module_number in (3, 4) and any(token in compact for token in ("CUM<SUB>2</SUB>", "G<SUB>2</SUB>", "CUM2", "G2", "FINAL<SUB>2</SUB>", "M3", "M4")):
            lines.append(clean_formula_line(line))
        elif module_number is None and any(token in compact for token in ("CUM", "G", "FINAL", "M1", "M2", "M3", "M4")):
            lines.append(clean_formula_line(line))

    return lines[:6]


def extract_formula_with_llm(
    *,
    subject_name: str,
    page_title: str,
    page_url: str,
    raw_text: str,
    module_number: int | None,
) -> dict | None:
    if not has_openai_api_key():
        return None

    prompt = {
        "subject_name": subject_name,
        "page_title": page_title,
        "current_module": module_number,
        "task": (
            "Extract only the grading formula from this wiki page. "
            "If there are separate formulas for modules 1-2 and 3-4, choose the one relevant to current_module. "
            "Return only formula lines, not long explanations. "
            "If no exact formula exists, return formula=null."
        ),
        "page_excerpt": extract_formula_section(raw_text),
        "return_json_schema": {
            "formula": "string|null",
            "formula_lines": ["string"],
            "reason": "short string",
            "is_exact": "boolean",
        },
    }

    try:
        result = call_openai_json(
            system_prompt="You extract grading formulas from HSE FKN wiki pages. Respond with JSON only.",
            user_payload=prompt,
        )
    except Exception:
        return None

    formula_lines = [
        clean_formula_line(line)
        for line in result.get("formula_lines", [])
        if isinstance(line, str) and line.strip()
    ]
    formula = clean_formula_line(result.get("formula", "")) if result.get("formula") else ""
    if not formula and formula_lines:
        formula = "\n".join(formula_lines)

    if not formula:
        return None

    return {
        "subject": subject_name,
        "page_title": page_title,
        "page_url": page_url,
        "formula": formula,
        "formula_lines": formula_lines,
        "source_label": "Wiki ФКН (LLM extract)",
        "is_exact": bool(result.get("is_exact", True)),
        "reason": result.get("reason", ""),
        "used_gpt": True,
    }


def find_subject_formula(
    *,
    subject_name: str,
    program_code: str,
    module_value: str | int | None = None,
    academic_year: str = DEFAULT_ACADEMIC_YEAR,
    use_gpt: bool = True,
) -> dict:
    if academic_year != DEFAULT_ACADEMIC_YEAR:
        raise ValueError(f"Сейчас модуль настроен на учебный год {DEFAULT_ACADEMIC_YEAR}.")

    page = locate_subject_page(subject_name, program_code)
    page_title = page["title"]
    page_url = wiki_page_url(page_title)
    raw_text = fetch_wiki_raw(page_title)
    module_number = parse_module_number(module_value)

    if not raw_text:
        return {
            "subject": subject_name,
            "page_title": page_title,
            "page_url": page_url,
            "formula": "Не удалось загрузить страницу предмета с wiki ФКН.",
            "formula_lines": [],
            "source_label": "Wiki ФКН",
            "is_exact": False,
            "reason": "Пустой ответ от wiki.",
            "used_gpt": False,
        }

    if use_gpt:
        llm_result = extract_formula_with_llm(
            subject_name=subject_name,
            page_title=page_title,
            page_url=page_url,
            raw_text=raw_text,
            module_number=module_number,
        )
        if llm_result:
            return llm_result

    fallback_lines = fallback_formula_lines(raw_text, module_number)
    if fallback_lines:
        return {
            "subject": subject_name,
            "page_title": page_title,
            "page_url": page_url,
            "formula": "\n".join(fallback_lines),
            "formula_lines": fallback_lines,
            "source_label": "Wiki ФКН (regex fallback)",
            "is_exact": False,
            "reason": "LLM недоступна или не вернула формулу, использован текстовый fallback.",
            "used_gpt": False,
        }

    return {
        "subject": subject_name,
        "page_title": page_title,
        "page_url": page_url,
        "formula": "Формула оценивания на открытой wiki-странице не найдена.",
        "formula_lines": [],
        "source_label": "Wiki ФКН",
        "is_exact": False,
        "reason": "На странице не удалось извлечь формулу ни через LLM, ни через fallback.",
        "used_gpt": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Извлечь формулу оценивания предмета с wiki ФКН.")
    parser.add_argument("--program", required=True, help="Код программы, например PAD / PI / PMI")
    parser.add_argument("--subject", required=True, help="Название предмета")
    parser.add_argument("--module", help="Текущий модуль, например '3 модуль' или '3'")
    parser.add_argument("--year", default=DEFAULT_ACADEMIC_YEAR, help="Учебный год, по умолчанию 2025/2026")
    parser.add_argument("--no-gpt", action="store_true", help="Не использовать GPT API")
    args = parser.parse_args()

    result = find_subject_formula(
        subject_name=args.subject,
        program_code=args.program,
        module_value=args.module,
        academic_year=args.year,
        use_gpt=not args.no_gpt,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
