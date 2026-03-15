from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass
from functools import lru_cache


WIKI_BASE_URL = "http://wiki.cs.hse.ru"
WIKI_HUB_TITLE = "Wiki ФКН"
DEFAULT_ACADEMIC_YEAR = "2025/2026"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

PROGRAM_SECTION_IDS = {
    "PMI": "AMI",
    "PI": "SE",
    "PAD": "DSBA",
    "KNAD": "compds",
    "EAD": "EDA",
    "DRIP": "DRIP",
}

PROGRAM_ALIASES = {
    "ПМИ": "PMI",
    "БПМИ": "PMI",
    "PMI": "PMI",
    "ПИ": "PI",
    "БПИ": "PI",
    "PI": "PI",
    "ПАД": "PAD",
    "БПАД": "PAD",
    "PAD": "PAD",
    "КНАД": "KNAD",
    "БКНАД": "KNAD",
    "KNAD": "KNAD",
    "ЭАД": "EAD",
    "БЭАД": "EAD",
    "EAD": "EAD",
    "ДРИП": "DRIP",
    "БДРИП": "DRIP",
    "DRIP": "DRIP",
}


@dataclass
class GradebookMatch:
    subject_name: str
    subject_page_title: str
    subject_page_url: str
    group: str
    google_sheet_url: str
    match_type: str
    source: str
    reason: str


def wiki_page_url(title: str) -> str:
    return f"{WIKI_BASE_URL}/{urllib.parse.quote(title.replace(' ', '_'))}"


def extract_urls(text: str) -> list[str]:
    return [
        url.rstrip(").,>")
        for url in re.findall(r"https://docs\.google\.com/spreadsheets/d/[A-Za-z0-9\-_]+(?:/[^\s\]<]*)?", text)
    ]


def normalize_program_code(program_code: str | None, group_name: str) -> str:
    if program_code:
        normalized = PROGRAM_ALIASES.get(program_code.strip().upper()) or PROGRAM_ALIASES.get(program_code.strip())
        if normalized:
            return normalized
        return program_code.strip().upper()

    for prefix, code in PROGRAM_ALIASES.items():
        if group_name.upper().startswith(prefix):
            return code

    raise ValueError("Не удалось определить программу. Передайте --program явно.")


def normalize_group(group_name: str) -> str:
    match = re.search(r"(\d{3}-\d)", group_name)
    if not match:
        raise ValueError("Не удалось извлечь группу. Ожидается формат вроде '257-1' или 'БПАД 257-1'.")

    return match.group(1)


@lru_cache(maxsize=64)
def fetch_wiki_raw(title: str) -> str:
    raw_url = f"{WIKI_BASE_URL}/index.php?{urllib.parse.urlencode({'title': title, 'action': 'raw'})}"
    try:
        with urllib.request.urlopen(raw_url, timeout=30) as response:
            return response.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def extract_program_section(hub_raw: str, section_id: str) -> str:
    pattern = re.compile(
        rf"\| colspan=\"4\" style=\"text-align: center;\" \| '''<span id=\"{re.escape(section_id)}\">.*?</span>'''(.*?)(?=\n\|-\n\| colspan=\"4\" style=\"text-align: center;\" \| '''<span id=\"|\n== )",
        re.S,
    )
    match = pattern.search(hub_raw)
    if not match:
        raise ValueError(f"Не удалось найти секцию программы {section_id} на wiki-хабе.")

    return match.group(1)


def extract_subject_pages(section_raw: str) -> list[dict[str, str]]:
    links = []
    seen_titles = set()

    for match in re.finditer(r"\[\[([^\]|#]+?)(?:#[^\]|]*)?(?:\s*\|\s*([^\]]+))?\]\]", section_raw):
        title = match.group(1).strip()
        label = (match.group(2) or title).strip()

        if not title or title in seen_titles:
            continue

        seen_titles.add(title)
        links.append(
            {
                "title": title,
                "label": label,
            }
        )

    return links


def find_exact_group_sheet(raw_text: str, group_code: str) -> str | None:
    return extract_exact_group_sheets(raw_text).get(group_code)


def extract_group_codes(raw_text: str) -> list[str]:
    return sorted(set(re.findall(r"\b\d{3}-\d\b", raw_text)))


def extract_exact_group_sheets(raw_text: str) -> dict[str, str]:
    matches: dict[str, str] = {}

    for line in raw_text.splitlines():
        if "docs.google.com/spreadsheets" not in line:
            continue

        stripped = line.strip()
        if not stripped.startswith("|"):
            continue

        first_cell = stripped[1:].split("||", 1)[0]
        groups = re.findall(r"\b\d{3}-\d\b", first_cell)
        if not groups:
            continue

        urls = extract_urls(line)
        if urls:
            for group in groups:
                matches[group] = urls[0]

    return matches


def find_shared_sheet(raw_text: str) -> tuple[str | None, str]:
    lines = raw_text.splitlines()
    positive_markers = ("results", "grades", "google table", "gradebook", "ведом", "оцен")
    negative_markers = ("telegram", "classroom", "register", "interview", "itinerary")

    for index, line in enumerate(lines):
        if "docs.google.com/spreadsheets" not in line:
            continue

        context = " ".join(lines[max(0, index - 1): min(len(lines), index + 2)])
        lowered = context.lower()
        if any(marker in lowered for marker in negative_markers):
            continue

        urls = extract_urls(context)
        if not urls:
            continue

        if any(marker in lowered for marker in positive_markers):
            return urls[0], context.strip()

    return None, ""


def build_relevant_excerpt(raw_text: str, group_code: str) -> str:
    group_bucket = group_code.split("-")[0]
    lines = raw_text.splitlines()
    selected_indexes = set()
    markers = (
        "docs.google.com/spreadsheets",
        group_code,
        group_bucket,
        "Results",
        "results",
        "grades",
        "google table",
        "Group",
        "Groups",
    )

    for index, line in enumerate(lines):
        if any(marker in line for marker in markers):
            for neighbor in range(max(0, index - 1), min(len(lines), index + 2)):
                selected_indexes.add(neighbor)

    if not selected_indexes:
        return raw_text[:5000]

    excerpt = "\n".join(lines[index] for index in sorted(selected_indexes))
    return excerpt[:12000]


def call_openai_for_gradebook(
    subject_name: str,
    subject_page_title: str,
    raw_text: str,
    group_code: str,
) -> dict | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    prompt = {
        "subject_name": subject_name,
        "subject_page_title": subject_page_title,
        "target_group": group_code,
        "page_excerpt": build_relevant_excerpt(raw_text, group_code),
        "task": (
            "Find the Google Sheets gradebook link for the target group. "
            "Return match_type=group_specific if the page has a dedicated sheet for the exact group. "
            "Return match_type=shared if there is only a common results/grades sheet for the course but it is still relevant to the target group. "
            "Return match_type=none if no relevant gradebook link exists. "
            "Ignore Telegram, Classroom, register, itinerary and interview links."
        ),
        "return_json_schema": {
            "selected_link": "string|null",
            "match_type": "group_specific|shared|none",
            "reason": "short string",
        },
    }

    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "You extract gradebook links from HSE FKN wiki pages. Respond with JSON only.",
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            },
        ],
    }

    request = urllib.request.Request(
        OPENAI_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.load(response)
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:
        return None


def collect_program_gradebooks(
    program_code: str,
    academic_year: str = DEFAULT_ACADEMIC_YEAR,
) -> dict:
    if academic_year != DEFAULT_ACADEMIC_YEAR:
        raise ValueError(f"Сейчас модуль настроен на учебный год {DEFAULT_ACADEMIC_YEAR}.")

    resolved_program = normalize_program_code(program_code, program_code)
    section_id = PROGRAM_SECTION_IDS.get(resolved_program)
    if not section_id:
        raise ValueError(f"Для программы {resolved_program} пока нет секции на wiki.")

    hub_raw = fetch_wiki_raw(WIKI_HUB_TITLE)
    section_raw = extract_program_section(hub_raw, section_id)
    subject_pages = extract_subject_pages(section_raw)

    known_groups: set[str] = set()
    exact_matches_by_group: dict[str, list[GradebookMatch]] = defaultdict(list)
    shared_matches: list[GradebookMatch] = []
    subject_payloads: list[dict] = []

    for subject_page in subject_pages:
        raw_text = fetch_wiki_raw(subject_page["title"])
        subject_name = subject_page["label"]
        page_title = subject_page["title"]
        page_url = wiki_page_url(page_title)

        discovered_groups = extract_group_codes(raw_text)
        known_groups.update(discovered_groups)

        exact_links = extract_exact_group_sheets(raw_text)
        for group_code, google_sheet_url in exact_links.items():
            exact_matches_by_group[group_code].append(
                GradebookMatch(
                    subject_name=subject_name,
                    subject_page_title=page_title,
                    subject_page_url=page_url,
                    group=group_code,
                    google_sheet_url=google_sheet_url,
                    match_type="group_specific",
                    source="wiki_regex",
                    reason=f"На странице найден отдельный Google Sheets ряд для группы {group_code}.",
                )
            )

        shared_link, shared_context = find_shared_sheet(raw_text)
        if shared_link:
            shared_matches.append(
                GradebookMatch(
                    subject_name=subject_name,
                    subject_page_title=page_title,
                    subject_page_url=page_url,
                    group="*",
                    google_sheet_url=shared_link,
                    match_type="shared",
                    source="wiki_regex_fallback",
                    reason=(
                        "На странице не нашлось отдельной ведомости по группам, "
                        "поэтому возвращена общая results/grades-таблица предмета. "
                        f"Контекст: {shared_context[:180]}"
                    ),
                )
            )

        subject_payloads.append(
            {
                "subject_name": subject_name,
                "subject_page_title": page_title,
                "subject_page_url": page_url,
                "raw_text": raw_text,
                "exact_group_links": exact_links,
                "shared_link": shared_link,
            }
        )

    return {
        "program_code": resolved_program,
        "academic_year": academic_year,
        "known_groups": sorted(known_groups),
        "exact_matches_by_group": exact_matches_by_group,
        "shared_matches": shared_matches,
        "subject_payloads": subject_payloads,
    }


def find_all_group_gradebooks(
    program_code: str,
    academic_year: str = DEFAULT_ACADEMIC_YEAR,
) -> dict:
    collected = collect_program_gradebooks(program_code=program_code, academic_year=academic_year)

    return {
        "program_code": collected["program_code"],
        "academic_year": collected["academic_year"],
        "known_groups": collected["known_groups"],
        "groups": {
            group_code: [asdict(match) for match in collected["exact_matches_by_group"].get(group_code, [])]
            for group_code in collected["known_groups"]
        },
        "shared_matches": [asdict(match) for match in collected["shared_matches"]],
    }


def find_group_gradebooks(
    group_name: str,
    program_code: str | None = None,
    academic_year: str = DEFAULT_ACADEMIC_YEAR,
    use_gpt: bool = True,
) -> dict:
    resolved_program = normalize_program_code(program_code, group_name)
    group_code = normalize_group(group_name)

    collected = collect_program_gradebooks(program_code=resolved_program, academic_year=academic_year)
    matches: list[GradebookMatch] = list(collected["exact_matches_by_group"].get(group_code, []))

    for shared_match in collected["shared_matches"]:
        matches.append(
            GradebookMatch(
                subject_name=shared_match.subject_name,
                subject_page_title=shared_match.subject_page_title,
                subject_page_url=shared_match.subject_page_url,
                group=group_code,
                google_sheet_url=shared_match.google_sheet_url,
                match_type=shared_match.match_type,
                source=shared_match.source,
                reason=shared_match.reason,
            )
        )

    if use_gpt and os.getenv("OPENAI_API_KEY"):
        seen_subjects = {match.subject_page_title for match in matches if match.match_type == "group_specific"}
        for subject_payload in collected["subject_payloads"]:
            page_title = subject_payload["subject_page_title"]
            raw_text = subject_payload["raw_text"]
            if page_title in seen_subjects or "docs.google.com/spreadsheets" not in raw_text:
                continue

            exact_link = find_exact_group_sheet(raw_text, group_code)
            if exact_link:
                continue

            subject_name = subject_payload["subject_name"]

            gpt_result = call_openai_for_gradebook(
                subject_name=subject_name,
                subject_page_title=page_title,
                raw_text=raw_text,
                group_code=group_code,
            )

            if gpt_result and gpt_result.get("selected_link"):
                matches.append(
                    GradebookMatch(
                        subject_name=subject_name,
                        subject_page_title=page_title,
                        subject_page_url=subject_payload["subject_page_url"],
                        group=group_code,
                        google_sheet_url=gpt_result["selected_link"],
                        match_type=gpt_result.get("match_type", "shared"),
                        source="gpt_api",
                        reason=gpt_result.get("reason", "Ссылка выбрана моделью по содержимому wiki-страницы."),
                    )
                )

    return {
        "program_code": resolved_program,
        "group": group_code,
        "academic_year": academic_year,
        "used_gpt": bool(use_gpt and os.getenv("OPENAI_API_KEY")),
        "matches": [asdict(match) for match in matches],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Найти ссылки на ведомости по группе через wiki ФКН.")
    parser.add_argument("--group", help="Например: 'БПАД 257-1' или '257-1'")
    parser.add_argument("--program", help="Код программы, например PAD / PI / PMI")
    parser.add_argument("--year", default=DEFAULT_ACADEMIC_YEAR, help="Учебный год, по умолчанию 2025/2026")
    parser.add_argument("--all-groups", action="store_true", help="Вернуть ссылки сразу для всех известных групп программы")
    parser.add_argument("--no-gpt", action="store_true", help="Отключить GPT API и использовать только локальный fallback")
    args = parser.parse_args()

    if args.all_groups:
        if not args.program:
            raise SystemExit("Для режима --all-groups передай --program, например PAD.")
        result = find_all_group_gradebooks(
            program_code=args.program,
            academic_year=args.year,
        )
    else:
        if not args.group:
            raise SystemExit("Передай --group, например 'БПАД 257-1', или используй --all-groups.")
        result = find_group_gradebooks(
            group_name=args.group,
            program_code=args.program,
            academic_year=args.year,
            use_gpt=not args.no_gpt,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
