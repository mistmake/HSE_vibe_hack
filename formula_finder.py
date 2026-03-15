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
    cleaned = re.sub(r"^[*#:;]+\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize_formula_signature(text: str) -> str:
    cleaned = clean_formula_line(text)
    cleaned = cleaned.upper()
    cleaned = cleaned.replace("'", "")
    cleaned = cleaned.replace("_", "")
    cleaned = re.sub(r"[^A-Z0-9=]+", "", cleaned)
    return cleaned


def looks_like_formula_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or "=" not in stripped:
        return False
    if re.match(r"^=+.*=+$", stripped):
        return False
    if stripped.startswith(("{|", "|}", "|-", "!", "|", "||")):
        return False

    cleaned = clean_formula_line(stripped)
    lowered = cleaned.lower()
    if any(marker in lowered for marker in ("http://", "https://", "docs.google.com", "telegram", "classroom")):
        return False

    if re.search(r"\b([A-Za-z][A-Za-z0-9_']{0,25})\s*=", cleaned):
        return True

    return "round(" in lowered and any(marker in lowered for marker in ("final course grade", "grade for the"))


def matches_any_token(signature: str, tokens: tuple[str, ...]) -> bool:
    return any(token in signature for token in tokens)


def heading_level(line: str) -> int | None:
    stripped = line.strip()
    match = re.match(r"^(=+).*(=+)$", stripped)
    if not match or len(match.group(1)) != len(match.group(2)):
        return None
    return len(match.group(1))


def extract_formula_variable(line: str) -> str:
    cleaned = clean_formula_line(line)
    segments = [cleaned]
    if ":" in cleaned:
        segments = list(reversed([segment.strip() for segment in cleaned.split(":")]))

    invalid_variables = {
        "GRADE",
        "GRADING",
        "SYSTEM",
        "SEMESTER",
        "MODULE",
        "FINALGRADE",
        "COURSEGRADE",
    }
    for segment in segments:
        match = re.search(r"\b([A-Za-z][A-Za-z0-9_']{0,40})\s*=", segment)
        if not match:
            continue
        variable = normalize_formula_signature(match.group(1))
        if variable and variable not in invalid_variables:
            return variable
    return ""


def extract_rhs_expression(line: str) -> str:
    cleaned = clean_formula_line(line)
    parts = cleaned.rsplit("=", 1)
    if len(parts) != 2:
        return ""
    return parts[1].strip()


def normalize_identifier(value: str) -> str:
    cleaned = clean_formula_line(value)
    cleaned = cleaned.replace("'", "_prime")
    cleaned = re.sub(r"[(){}\[\]]+", "_", cleaned)
    cleaned = cleaned.replace("&", "_")
    cleaned = cleaned.replace("/", "_")
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return ""
    if cleaned[0].isdigit():
        cleaned = f"v_{cleaned}"
    return cleaned


def dedupe_strings(values: list[str]) -> list[str]:
    unique_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = clean_formula_line(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique_values.append(cleaned)
    return unique_values


def prepare_formula_context_for_llm(raw_text: str) -> str:
    section = extract_formula_section(raw_text)
    cleaned_lines: list[str] = []
    for raw_line in section.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(("{|", "|}", "|-", "!", "|", "||")):
            continue
        cleaned = clean_formula_line(raw_line)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if any(
            marker in lowered
            for marker in ("telegram", "classroom", "docs.google.com", "drive.google.com", "zoom")
        ) and "=" not in cleaned:
            continue
        cleaned_lines.append(cleaned)

    excerpt = "\n".join(cleaned_lines).strip()
    if excerpt:
        return excerpt[:16000]

    raw_excerpt_lines = []
    for raw_line in raw_text.splitlines():
        cleaned = clean_formula_line(raw_line)
        if cleaned:
            raw_excerpt_lines.append(cleaned)
    return "\n".join(raw_excerpt_lines)[:16000]


def normalize_formula_target(raw_target: dict | None) -> dict:
    raw_target = raw_target if isinstance(raw_target, dict) else {}
    variable = clean_formula_line(raw_target.get("variable", ""))
    expression = clean_formula_line(raw_target.get("expression", "")) or extract_rhs_expression(
        raw_target.get("full_formula", "")
    )
    full_formula = clean_formula_line(raw_target.get("full_formula", ""))

    if full_formula and not variable:
        variable = extract_formula_variable(full_formula)
    if variable and expression and not full_formula:
        full_formula = f"{variable} = {expression}"

    alias = normalize_identifier(
        raw_target.get("alias", "")
        or raw_target.get("normalized_variable", "")
        or variable
    )
    return {
        "variable": variable,
        "alias": alias,
        "expression": expression,
        "full_formula": full_formula,
        "label": clean_formula_line(raw_target.get("label", "")),
        "module_scope": clean_formula_line(raw_target.get("module_scope", "")),
        "description": clean_formula_line(raw_target.get("description", "")),
    }


def normalize_formula_step(raw_step: dict) -> dict | None:
    if not isinstance(raw_step, dict):
        return None

    variable = clean_formula_line(raw_step.get("variable", ""))
    expression = clean_formula_line(raw_step.get("expression", "")) or clean_formula_line(
        raw_step.get("rhs_expression", "")
    )
    full_formula = clean_formula_line(raw_step.get("full_formula", "")) or clean_formula_line(
        raw_step.get("formula", "")
    )

    if full_formula and not variable:
        variable = extract_formula_variable(full_formula)
    if full_formula and not expression:
        expression = extract_rhs_expression(full_formula)
    if variable and expression and not full_formula:
        full_formula = f"{variable} = {expression}"

    if not variable and not full_formula:
        return None

    depends_on = dedupe_strings(
        [
            item
            for item in raw_step.get("depends_on", [])
            if isinstance(item, str)
        ]
    )
    kind = clean_formula_line(raw_step.get("kind", "")).lower()
    if kind not in {"input", "derived", "target", "final"}:
        kind = "derived"

    return {
        "variable": variable,
        "alias": normalize_identifier(
            raw_step.get("alias", "")
            or raw_step.get("normalized_variable", "")
            or variable
        ),
        "expression": expression,
        "full_formula": full_formula,
        "normalized_expression": clean_formula_line(raw_step.get("normalized_expression", "")),
        "depends_on": depends_on,
        "kind": kind,
        "module_scope": clean_formula_line(raw_step.get("module_scope", "")),
        "description": clean_formula_line(raw_step.get("description", "")),
    }


def normalize_input_variable(raw_item: dict | str) -> dict | None:
    if isinstance(raw_item, str):
        variable = clean_formula_line(raw_item)
        if not variable:
            return None
        return {
            "variable": variable,
            "alias": normalize_identifier(variable),
            "label": variable,
            "description": "",
            "expected_range": "",
        }

    if not isinstance(raw_item, dict):
        return None

    variable = clean_formula_line(raw_item.get("variable", "")) or clean_formula_line(raw_item.get("symbol", ""))
    if not variable:
        return None

    return {
        "variable": variable,
        "alias": normalize_identifier(
            raw_item.get("alias", "")
            or raw_item.get("normalized_variable", "")
            or variable
        ),
        "label": clean_formula_line(raw_item.get("label", "")) or variable,
        "description": clean_formula_line(raw_item.get("description", "")),
        "expected_range": clean_formula_line(raw_item.get("expected_range", "")),
    }


def apply_aliases(text: str, alias_map: dict[str, str]) -> str:
    normalized = clean_formula_line(text)
    for original in sorted(alias_map, key=len, reverse=True):
        alias = alias_map[original]
        if original and alias:
            normalized = normalized.replace(original, alias)
    return normalized


def finalize_formula_payload(
    *,
    subject_name: str,
    page_title: str,
    page_url: str,
    source_label: str,
    is_exact: bool,
    reason: str,
    used_gpt: bool,
    formula: str,
    formula_lines: list[str],
    selected_target: dict | None = None,
    final_target: dict | None = None,
    formula_chain: list[dict] | None = None,
    input_variables: list[dict] | None = None,
) -> dict:
    selected_target_data = normalize_formula_target(selected_target)
    final_target_data = normalize_formula_target(final_target)

    normalized_chain = [
        step
        for step in (normalize_formula_step(item) for item in (formula_chain or []))
        if step
    ]
    normalized_inputs = [
        item
        for item in (normalize_input_variable(raw_item) for raw_item in (input_variables or []))
        if item
    ]

    derived_variables = {step["variable"] for step in normalized_chain if step["variable"]}
    known_inputs = {item["variable"] for item in normalized_inputs}
    for step in normalized_chain:
        for dependency in step["depends_on"]:
            if dependency not in derived_variables and dependency not in known_inputs:
                normalized_inputs.append(
                    {
                        "variable": dependency,
                        "alias": normalize_identifier(dependency),
                        "label": dependency,
                        "description": "",
                        "expected_range": "",
                    }
                )
                known_inputs.add(dependency)

    alias_map = {
        item["variable"]: item["alias"]
        for item in normalized_inputs
        if item["variable"] and item["alias"]
    }
    alias_map.update(
        {
            step["variable"]: step["alias"]
            for step in normalized_chain
            if step["variable"] and step["alias"]
        }
    )
    for target in (selected_target_data, final_target_data):
        if target["variable"] and target["alias"]:
            alias_map[target["variable"]] = target["alias"]

    for step in normalized_chain:
        if not step["normalized_expression"]:
            expression_source = step["expression"] or step["full_formula"]
            step["normalized_expression"] = apply_aliases(expression_source, alias_map)

    if selected_target_data["full_formula"] and not selected_target_data["expression"]:
        selected_target_data["expression"] = extract_rhs_expression(selected_target_data["full_formula"])
    if final_target_data["full_formula"] and not final_target_data["expression"]:
        final_target_data["expression"] = extract_rhs_expression(final_target_data["full_formula"])

    normalized_formula_lines = dedupe_strings(formula_lines)
    if not normalized_formula_lines and normalized_chain:
        normalized_formula_lines = dedupe_strings(
            [step["full_formula"] or step["expression"] for step in normalized_chain if step["full_formula"] or step["expression"]]
        )
    if not normalized_formula_lines and selected_target_data["full_formula"]:
        normalized_formula_lines = [selected_target_data["full_formula"]]
    if not normalized_formula_lines and final_target_data["full_formula"]:
        normalized_formula_lines = [final_target_data["full_formula"]]

    resolved_formula = clean_formula_line(formula)
    if not resolved_formula and normalized_formula_lines:
        resolved_formula = "\n".join(normalized_formula_lines)

    return {
        "subject": subject_name,
        "page_title": page_title,
        "page_url": page_url,
        "formula": resolved_formula,
        "formula_lines": normalized_formula_lines,
        "selected_target": selected_target_data,
        "final_target": final_target_data,
        "formula_chain": normalized_chain,
        "input_variables": normalized_inputs,
        "calculation_ready": bool(normalized_chain and (selected_target_data["variable"] or final_target_data["variable"])),
        "source_label": source_label,
        "is_exact": is_exact,
        "reason": clean_formula_line(reason),
        "used_gpt": used_gpt,
    }


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
    preferred_markers = (
        "grading system",
        "assessment and grading",
        "grading",
        "assessment",
        "evaluation",
        "formula",
        "grades",
        "оцен",
        "формул",
    )

    marker_keys = tuple(normalize_subject_key(marker) for marker in preferred_markers)

    for marker, marker_key in zip(preferred_markers, marker_keys):
        collected: list[str] = []
        capture = False
        marker_level: int | None = None

        for line in lines:
            stripped = line.strip()
            current_level = heading_level(stripped)
            is_heading = current_level is not None
            heading_key = normalize_subject_key(stripped)

            if is_heading and marker_key and marker_key in heading_key:
                capture = True
                marker_level = current_level
                collected.append(line)
                continue

            if capture and is_heading and marker_level is not None and current_level <= marker_level:
                break

            if capture:
                collected.append(line)

        if collected:
            return "\n".join(collected)[:12000]

    relevant = []
    for line in lines:
        lowered = clean_formula_line(line).lower()
        stripped = line.strip()
        if stripped.startswith(("{|", "|}", "|-", "!", "|", "||")):
            continue
        if looks_like_formula_line(line) or any(
            marker in lowered
            for marker in ("cum", "exam", "final", "grade", "formula", "interim", "round(", "bonus", "colloq")
        ):
            relevant.append(line)

    if relevant:
        return "\n".join(relevant)[:12000]

    return raw_text[:12000]


def fallback_formula_lines(raw_text: str, module_number: int | None) -> list[str]:
    relevant_text = extract_formula_section(raw_text)
    formula_entries: list[tuple[str, str, str]] = []
    for raw_line in relevant_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        lowered = clean_formula_line(line).lower()
        if any(marker in lowered for marker in ("classroom", "telegram", "google.com", "links", "tg:")):
            continue

        if looks_like_formula_line(line):
            cleaned = clean_formula_line(line)
            formula_entries.append((cleaned, normalize_formula_signature(cleaned), extract_formula_variable(cleaned)))
            continue

    if not formula_entries:
        return []

    early_primary_tokens = (
        "CUM1",
        "G1",
        "FINAL1",
        "MID1",
        "EXAM1",
        "INTERIM1",
        "C1",
        "I1",
    )
    early_secondary_tokens = (
        "GCUMULATIVE",
        "HWA",
    )
    late_primary_tokens = (
        "CUM2",
        "G2",
        "FINAL2",
        "GFINAL",
        "FINAL",
        "MID2",
        "EXAM2",
        "INTERIM2",
        "C2",
        "I2",
        "HWB",
        "HWTESTB",
        "COLLOQ",
        "BONUS",
        "F",
    )
    late_secondary_tokens = (
        "GCUMULATIVE",
    )
    selected: list[str] = []
    seen: set[str] = set()

    def add_matching(tokens: tuple[str, ...], *, use_signature: bool = False) -> None:
        for cleaned, signature, variable in formula_entries:
            if cleaned in seen:
                continue
            lowered_cleaned = cleaned.lower()
            if not variable and module_number in (1, 2) and any(
                marker in lowered_cleaned for marker in ("final course grade", "final grade")
            ):
                continue
            if variable and not use_signature:
                matched = variable in tokens
            else:
                matched = matches_any_token(signature, tokens)
            if matched:
                selected.append(cleaned)
                seen.add(cleaned)

    if module_number in (1, 2):
        add_matching(early_primary_tokens)
        if len(selected) < 2:
            add_matching(early_secondary_tokens)
    elif module_number in (3, 4):
        add_matching(late_primary_tokens)
        if len(selected) < 2:
            add_matching(late_secondary_tokens)
    else:
        for cleaned, _signature, _variable in formula_entries:
            if cleaned in seen:
                continue
            selected.append(cleaned)
            seen.add(cleaned)

    if len(selected) < 2:
        for cleaned, _signature, _variable in formula_entries:
            if cleaned in seen:
                continue
            selected.append(cleaned)
            seen.add(cleaned)
            if len(selected) >= 6:
                break

    return selected[:8]


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

    context_excerpt = prepare_formula_context_for_llm(raw_text)
    prompt = {
        "subject_name": subject_name,
        "page_title": page_title,
        "page_url": page_url,
        "current_module": module_number,
        "task": [
            "Extract the grading formulas from this HSE FKN wiki page.",
            "Use GPT as the main parser and prefer exact equations from the page.",
            "Choose the formula track relevant to current_module. Modules 1-2 mean the first-semester track, modules 3-4 mean the second-semester or final-course track.",
            "Return a machine-friendly JSON payload so another script can calculate the grade from student inputs.",
            "Do not invent formulas. If the page does not contain enough information, return formula=null and empty arrays.",
        ],
        "page_excerpt": context_excerpt,
        "return_json_schema": {
            "formula": "string|null",
            "formula_lines": ["string"],
            "selected_target": {
                "variable": "string",
                "alias": "string",
                "expression": "string",
                "full_formula": "string",
                "label": "string",
                "module_scope": "string",
                "description": "string",
            },
            "final_target": {
                "variable": "string",
                "alias": "string",
                "expression": "string",
                "full_formula": "string",
                "label": "string",
                "module_scope": "string",
                "description": "string",
            },
            "formula_chain": [
                {
                    "variable": "string",
                    "alias": "string",
                    "expression": "string",
                    "full_formula": "string",
                    "normalized_expression": "string",
                    "depends_on": ["string"],
                    "kind": "input|derived|target|final",
                    "module_scope": "string",
                    "description": "string",
                }
            ],
            "input_variables": [
                {
                    "variable": "string",
                    "alias": "string",
                    "label": "string",
                    "description": "string",
                    "expected_range": "string",
                }
            ],
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

    normalized_result = finalize_formula_payload(
        subject_name=subject_name,
        page_title=page_title,
        page_url=page_url,
        source_label="Wiki ФКН (GPT parser)",
        is_exact=bool(result.get("is_exact", True)),
        reason=result.get("reason", ""),
        used_gpt=True,
        formula=result.get("formula", "") or "",
        formula_lines=[
            line
            for line in result.get("formula_lines", [])
            if isinstance(line, str) and line.strip()
        ],
        selected_target=result.get("selected_target"),
        final_target=result.get("final_target"),
        formula_chain=result.get("formula_chain"),
        input_variables=result.get("input_variables"),
    )

    if not normalized_result["formula"] and not normalized_result["formula_chain"]:
        return None

    return normalized_result


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
        return finalize_formula_payload(
            subject_name=subject_name,
            page_title=page_title,
            page_url=page_url,
            source_label="Wiki ФКН",
            is_exact=False,
            reason="Пустой ответ от wiki.",
            used_gpt=False,
            formula="Не удалось загрузить страницу предмета с wiki ФКН.",
            formula_lines=[],
        )

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
        return finalize_formula_payload(
            subject_name=subject_name,
            page_title=page_title,
            page_url=page_url,
            source_label="Wiki ФКН (fallback parser)",
            is_exact=False,
            reason="GPT parser недоступен или не вернул пригодную структуру, использован резервный текстовый разбор.",
            used_gpt=False,
            formula="\n".join(fallback_lines),
            formula_lines=fallback_lines,
        )

    return finalize_formula_payload(
        subject_name=subject_name,
        page_title=page_title,
        page_url=page_url,
        source_label="Wiki ФКН",
        is_exact=False,
        reason="На странице не удалось извлечь формулу ни через GPT parser, ни через fallback.",
        used_gpt=False,
        formula="Формула оценивания на открытой wiki-странице не найдена.",
        formula_lines=[],
    )


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
