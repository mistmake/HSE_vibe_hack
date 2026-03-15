import html
import re
import time
import urllib.request
from functools import lru_cache

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from formula_finder import find_subject_formula
from gradebook_finder import (
    DEFAULT_ACADEMIC_YEAR,
    PROGRAM_SECTION_IDS,
    WIKI_HUB_TITLE,
    extract_program_section,
    fetch_wiki_raw,
    find_subject_gradebook,
)


app = FastAPI(title="HSE Vibe Hack")
app.add_middleware(SessionMiddleware, secret_key="hackathon-demo-secret")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

STATEMENT_URL = "https://my.hse.ru/"


PROGRAMS = [
    {
        "code": "PI",
        "name": "Программная инженерия",
        "tutors_url": "https://www.hse.ru/ba/se/tutors",
    },
    {
        "code": "PMI",
        "name": "Прикладная математика и информатика",
        "tutors_url": "https://www.hse.ru/ba/ami/tutors",
    },
    {
        "code": "PAD",
        "name": "Прикладной анализ данных",
        "tutors_url": "https://www.hse.ru/ba/data/tutors",
    },
    {
        "code": "KNAD",
        "name": "Компьютерные науки и анализ данных",
        "tutors_url": "https://www.hse.ru/ba/compds/tutors",
    },
    {
        "code": "DRIP",
        "name": "Дизайн и разработка информационных продуктов",
        "tutors_url": "https://www.hse.ru/ba/drip/tutors",
    },
]

PROGRAM_BY_CODE = {program["code"]: program for program in PROGRAMS}
COURSES = ["1 курс", "2 курс", "3 курс", "4 курс"]
MODULES = ["1 модуль", "2 модуль", "3 модуль", "4 модуль"]

FALLBACK_SUBJECTS = {
    "PI": {
        "1 курс": {
            "1 модуль": [
                "Алгебра",
                "Математический анализ",
                "Введение в программную инженерию",
                "История России",
            ],
            "2 модуль": [
                "Алгебра",
                "Математический анализ",
                "Введение в программную инженерию",
                "Алгоритмы и алгоритмические языки",
            ],
            "3 модуль": [
                "Основы программирования на C++",
                "Дискретная математика",
                "Линейная алгебра и геометрия",
                "Английский язык",
            ],
            "4 модуль": [
                "Основы программирования на C++",
                "English Language Integrative Exam",
                "Линейная алгебра и геометрия",
                "Математический анализ",
            ],
        },
        "2 курс": {
            "1 модуль": [
                "Алгоритмы и структуры данных",
                "Архитектура компьютера и операционные системы",
                "Теория вероятностей",
                "Научно-исследовательский семинар \"Основы веб-разработки на PHP\"",
            ],
            "2 модуль": [
                "Алгоритмы и структуры данных",
                "Архитектура компьютера и операционные системы",
                "Теория вероятностей",
                "Научно-исследовательский семинар \"Основы веб-разработки на PHP\"",
            ],
            "3 модуль": [
                "Алгоритмы и структуры данных",
                "Архитектура компьютера и операционные системы",
                "Научно-исследовательский семинар \"Основы веб-разработки на PHP\"",
                "Независимый экзамен по программированию. Продвинутый уровень",
            ],
            "4 модуль": [
                "Алгоритмы и структуры данных",
                "Архитектура компьютера и операционные системы",
                "Независимый экзамен по программированию. Продвинутый уровень",
                "English Language Integrative Exam",
            ],
        },
    },
    "PMI": {
        "1 курс": {
            "1 модуль": [
                "Линейная алгебра и геометрия",
                "Математический анализ",
                "История России",
                "Английский язык",
            ],
            "2 модуль": [
                "Линейная алгебра и геометрия",
                "Математический анализ",
                "История России",
                "Английский язык",
            ],
            "3 модуль": [
                "Математический анализ",
                "Дискретная математика (углубленный курс)",
                "Английский язык",
                "Основы российской государственности",
            ],
            "4 модуль": [
                "Алгебра",
                "Алгебра (углубленный курс)",
                "Линейная алгебра и геометрия",
                "Английский язык",
            ],
        }
    },
    "PAD": {
        "1 курс": {
            "1 модуль": [
                "English Language",
                "Russian History",
                "Physical Training",
                "Основы российской государственности",
            ],
            "2 модуль": [
                "English Language",
                "Russian History",
                "Physical Training",
                "Основы российской государственности",
            ],
            "3 модуль": [
                "English Language",
                "Russian History",
                "Physical Training",
                "Основы российской государственности",
            ],
            "4 модуль": [
                "English Language",
                "English Language Integrative Exam",
                "Russian History",
                "Physical Training",
            ],
        },
        "2 курс": {
            "1 модуль": [
                "Discrete Mathematics 2",
                "Теория вероятностей",
                "Python Programming Language (advanced course)",
                "Physical Training",
            ],
            "2 модуль": [
                "Discrete Mathematics 2",
                "Теория вероятностей",
                "Python Programming Language (advanced course)",
                "Physical Training",
            ],
            "3 модуль": [
                "Machine Learning 1",
                "Mathematical Statistics",
                "Physical Training",
                "Machine Learning 1",
            ],
            "4 модуль": [
                "Machine Learning 1",
                "Mathematical Statistics",
                "Physical Training",
                "English Language Integrative Exam",
            ],
        },
    },
    "KNAD": {
        "1 курс": {
            "1 модуль": [
                "Algebra",
                "Linear Algebra",
                "Математический анализ",
                "Russian History",
            ],
            "2 модуль": [
                "Algorithms and Data Structures",
                "Algebra",
                "Linear Algebra",
                "Математический анализ",
            ],
            "3 модуль": [
                "Python as a Tool for Data Collection and Analysis",
                "Discrete Mathematics",
                "Modern Software Engineering Practices",
                "Программирование на языке С++",
            ],
            "4 модуль": [
                "Algorithms and Data Structures",
                "Discrete Mathematics",
                "English Language Integrative Exam",
                "Modern Software Engineering Practices",
            ],
        },
        "2 курс": {
            "1 модуль": [
                "Алгебра",
                "Physical Training",
                "Теория вероятностей",
                "Machine Learning 1",
            ],
            "2 модуль": [
                "Алгебра",
                "Physical Training",
                "Теория вероятностей",
                "Machine Learning 1",
            ],
            "3 модуль": [
                "Machine Learning 1",
                "Архитектура компьютера и операционные системы",
                "Physical Training",
                "Advanced Statistics 2",
            ],
            "4 модуль": [
                "Machine Learning 1",
                "Архитектура компьютера и операционные системы",
                "Physical Training",
                "English Language Integrative Exam",
            ],
        },
    },
    "DRIP": {
        "1 курс": {
            "1 модуль": [
                "Язык программирования C++",
                "Дискретная математика",
                "Математический анализ",
                "История России",
            ],
            "2 модуль": [
                "Язык программирования C++",
                "Дискретная математика",
                "Математический анализ",
                "История России",
            ],
            "3 модуль": [
                "Язык программирования Java",
                "Алгоритмы и структуры данных 1",
                "Проектная работа",
                "Английский язык",
            ],
            "4 модуль": [
                "Язык программирования Java",
                "Алгоритмы и структуры данных 1",
                "Проектная работа",
                "English Language Integrative Exam",
            ],
        }
    },
}

def build_formula_info(name: str, index: int, module_value: str) -> dict:
    return {
        "formula": "Формула будет загружена с wiki ФКН для выбранного предмета",
        "source_url": "",
        "source_label": "",
        "is_exact": False,
    }


def make_subject(name: str, index: int, module_value: str) -> dict:
    scores = ["4.5", "5.2", "4.8", "5.4", "4.9", "5.1"]
    ranks = ["56/220", "41/220", "63/220", "34/220", "52/220", "48/220"]
    formula_info = build_formula_info(name, index, module_value)
    return {
        "name": name,
        "local_rank": ranks[index % len(ranks)],
        "score": scores[index % len(scores)],
        "formula": formula_info["formula"],
        "formula_source_url": formula_info["source_url"],
        "formula_source_label": formula_info["source_label"],
        "formula_is_exact": formula_info["is_exact"],
        "gradebook_url": "",
        "gradebook_subject_page_url": "",
        "gradebook_source_label": "",
        "gradebook_reason": "",
        "gradebook_match_type": "",
        "gradebook_available": False,
    }


def parse_course_number(value: str) -> int:
    match = re.search(r"\d+", value)
    return int(match.group()) if match else 1


def parse_module_number(value: str) -> int:
    match = re.search(r"\d+", value)
    return int(match.group()) if match else 1


def parse_module_list(raw_modules: str) -> list[int]:
    numbers = [int(item) for item in re.findall(r"\d+", raw_modules)]
    if not numbers:
        return []
    if len(numbers) == 2 and "-" in raw_modules:
        start, end = numbers
        if start <= end:
            return list(range(start, end + 1))
    return sorted(set(numbers))


def extract_modules_from_text(text: str) -> list[int]:
    patterns = [
        re.compile(r"modules?\s*\(?\s*([0-9,\s\-–]+)", flags=re.IGNORECASE),
        re.compile(r"\(?\s*([0-9,\s\-–]+)\s*\)?\s*модул", flags=re.IGNORECASE),
    ]

    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return parse_module_list(match.group(1).replace("–", "-"))

    return []


def clean_subject_name(raw_value: str) -> str:
    cleaned = raw_value.replace("_", " ")
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -\t")
    return cleaned


def extract_subject_labels_from_line(line: str) -> list[str]:
    labels = []

    for match in re.finditer(r"\[\[([^\]|#]+?)(?:#[^\]|]*)?(?:\s*\|\s*([^\]]+))?\]\]", line):
        label = clean_subject_name(match.group(2) or match.group(1))
        if label:
            labels.append(label)

    for match in re.finditer(r"\[(https?://[^\s\]]+)\s+([^\]]+)\]", line):
        label = clean_subject_name(match.group(2))
        if label:
            labels.append(label)

    return labels


def split_program_cells(section_raw: str) -> list[str]:
    cells = []
    current_cell: list[str] = []

    for raw_line in section_raw.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("|-"):
            continue

        if stripped.startswith("| colspan="):
            break

        if stripped.startswith("||"):
            if current_cell:
                cells.append("\n".join(current_cell).strip())
            current_cell = [stripped[2:].lstrip()]
            continue

        if stripped == "|" or re.match(r"^\|(?:\s|$)", stripped):
            if current_cell:
                cells.append("\n".join(current_cell).strip())
            current_cell = [re.sub(r"^\|\s?", "", stripped)]
            continue

        current_cell.append(line)

    if current_cell:
        cells.append("\n".join(current_cell).strip())

    return [cell for cell in cells if cell and cell != "&nbsp;"]


def load_subjects_from_wiki_hub(program_code: str, course_number: int, module_number: int) -> list[str]:
    section_id = PROGRAM_SECTION_IDS.get(program_code)
    if not section_id:
        return []

    hub_raw = fetch_wiki_raw(WIKI_HUB_TITLE)
    if not hub_raw:
        return []

    try:
        section_raw = extract_program_section(hub_raw, section_id)
    except ValueError:
        return []

    course_cells = split_program_cells(section_raw)
    if course_number < 1 or course_number > len(course_cells):
        return []

    target_cell = course_cells[course_number - 1]
    subjects = []
    seen = set()
    active_modules: list[int] = []

    for raw_line in target_cell.splitlines():
        line = raw_line.strip()
        if not line or line == "&nbsp;":
            continue

        if line.startswith("'''"):
            active_modules = extract_modules_from_text(line)
            continue

        labels = extract_subject_labels_from_line(line)
        if not labels:
            continue

        line_modules = extract_modules_from_text(line)
        effective_modules = line_modules or active_modules
        if effective_modules and module_number not in effective_modules:
            continue

        for label in labels:
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            subjects.append(label)

    return subjects


def html_to_text(raw_html: str) -> str:
    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw_html)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?s)<[^>]+>", "\n", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = cleaned.replace("\xa0", " ")
    return cleaned


def parse_courses_from_text(text: str, course_number: int, module_number: int) -> list[str]:
    subjects = []
    seen = set()
    patterns = [
        re.compile(
            r"(?P<title>[^\n()]{3,}?)\s*\((?P<course>\d)[-–]?(?:й)?\s*курс,\s*(?P<modules>[^)]*?модул[^)]*)\)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"(?P<title>[^\n()]{3,}?)\s*\((?P<course>\d)\s*year,\s*(?P<modules>[^)]*?module[^)]*)\)",
            flags=re.IGNORECASE,
        ),
    ]

    for pattern in patterns:
        for match in pattern.finditer(text):
            title = re.sub(r"\s+", " ", match.group("title")).strip(" -\n\t")
            parsed_course = int(match.group("course"))
            modules = parse_module_list(match.group("modules"))

            if parsed_course != course_number or module_number not in modules:
                continue

            if len(title) < 3 or len(title) > 120:
                continue

            if title.lower() in seen:
                continue

            seen.add(title.lower())
            subjects.append(title)

    return subjects


@lru_cache(maxsize=32)
def fetch_page(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    request = urllib.request.Request(url, headers=headers)

    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            last_error = exc
            time.sleep(0.35 * (attempt + 1))

    raise last_error


def load_real_subjects(program_code: str, course_value: str, module_value: str) -> list[dict]:
    program = PROGRAM_BY_CODE.get(program_code)
    if not program:
        return [make_subject(name, index, "1 модуль") for index, name in enumerate(FALLBACK_SUBJECTS["PI"]["1 курс"]["1 модуль"])]

    course_number = parse_course_number(course_value)
    module_number = parse_module_number(module_value)
    names = load_subjects_from_wiki_hub(program_code, course_number, module_number)

    if not names:
        try:
            raw_page = fetch_page(program["tutors_url"])
            text = html_to_text(raw_page)
            names = parse_courses_from_text(text, course_number, module_number)
        except Exception:
            names = []

    if not names:
        fallback_names = (
            FALLBACK_SUBJECTS.get(program_code, {})
            .get(course_value, {})
            .get(module_value, [])
        )
        names = fallback_names

    if not names:
        names = ["Предметы по выбранной комбинации пока не найдены"]

    unique_names = []
    seen = set()
    for name in names:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            unique_names.append(name)

    return [make_subject(name, index, module_value) for index, name in enumerate(unique_names)]


def get_selected_subject(subject: str | None, subjects: list[dict]):
    try:
        selected_index = int(subject or "1") - 1
    except ValueError:
        selected_index = 0

    if selected_index < 0 or selected_index >= len(subjects):
        selected_index = 0

    return selected_index, subjects[selected_index]


def enrich_subject_formula(subject_data: dict, direction_code: str, module_value: str) -> dict:
    enriched = dict(subject_data)

    try:
        formula_result = find_subject_formula(
            subject_name=subject_data["name"],
            program_code=direction_code,
            module_value=module_value,
            use_gpt=True,
        )
    except Exception:
        formula_result = None

    if not formula_result:
        return enriched

    enriched["formula"] = formula_result["formula"]
    enriched["formula_lines"] = formula_result.get("formula_lines", [])
    enriched["formula_source_url"] = formula_result["page_url"]
    enriched["formula_source_label"] = formula_result["source_label"]
    enriched["formula_is_exact"] = formula_result["is_exact"]
    enriched["formula_used_gpt"] = formula_result.get("used_gpt", False)
    enriched["formula_selected_target"] = formula_result.get("selected_target", {})
    enriched["formula_final_target"] = formula_result.get("final_target", {})
    enriched["formula_chain"] = formula_result.get("formula_chain", [])
    enriched["formula_input_variables"] = formula_result.get("input_variables", [])
    enriched["formula_calculation_ready"] = formula_result.get("calculation_ready", False)
    return enriched


def enrich_subject_gradebook(subject_data: dict, direction_code: str, group_number: str) -> dict:
    enriched = dict(subject_data)

    if not group_number:
        return enriched

    try:
        gradebook_result = find_subject_gradebook(
            subject_name=subject_data["name"],
            group_name=group_number,
            program_code=direction_code,
            use_gpt=True,
        )
    except Exception:
        gradebook_result = None

    if not gradebook_result:
        return enriched

    gradebook = gradebook_result["gradebook"]
    enriched["gradebook_url"] = gradebook["google_sheet_url"]
    enriched["gradebook_subject_page_url"] = gradebook["subject_page_url"]
    enriched["gradebook_source_label"] = "Ведомость из wiki ФКН"
    enriched["gradebook_reason"] = gradebook["reason"]
    enriched["gradebook_match_type"] = gradebook["match_type"]
    enriched["gradebook_available"] = True
    return enriched


def build_program_payload() -> list[dict]:
    return [{"code": program["code"], "name": program["name"]} for program in PROGRAMS]


def build_subject_payload(direction_code: str, course_value: str, module_value: str) -> dict:
    subjects = load_real_subjects(direction_code, course_value, module_value)
    selected_index, selected_subject = get_selected_subject(None, subjects)
    return {
        "direction_code": direction_code,
        "direction_name": PROGRAM_BY_CODE.get(direction_code, {}).get("name", direction_code),
        "course": course_value,
        "current_module": module_value,
        "automats": [item["name"] for item in subjects[:4]],
        "subjects": subjects,
        "selected_index": selected_index,
        "selected_subject": selected_subject,
    }


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "full_name": "",
            "group_number": "",
            "direction": "",
            "course": "",
            "current_module": "",
            "programs": PROGRAMS,
            "courses": COURSES,
            "modules": MODULES,
        },
    )


@app.get("/api/programs")
async def programs_api():
    return {"programs": build_program_payload()}


@app.get("/api/subjects")
async def subjects_api(
    direction: str = "PI",
    course: str = "1 курс",
    current_module: str = "1 модуль",
):
    direction_code = direction.strip().upper()
    return build_subject_payload(direction_code, course, current_module)


@app.get("/api/subjects/formula")
async def subject_formula_api(
    request: Request,
    subject: str = Query(..., description="Название предмета, например 'Calculus 1'"),
    direction: str | None = Query(None, description="Код программы, например PAD / PI / PMI"),
    current_module: str | None = Query(None, description="Текущий модуль, например '3 модуль'"),
    use_gpt: bool = Query(True, description="Использовать GPT API как основной парсер формулы"),
):
    direction_code = (direction or request.session.get("direction", "PI")).strip().upper()
    module_value = (current_module or request.session.get("current_module", "1 модуль")).strip()

    try:
        formula_result = find_subject_formula(
            subject_name=subject.strip(),
            program_code=direction_code,
            module_value=module_value,
            use_gpt=use_gpt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось получить формулу с wiki: {exc}") from exc

    return {
        "subject": subject.strip(),
        "direction_code": direction_code,
        "current_module": module_value,
        "formula": formula_result["formula"],
        "formula_lines": formula_result["formula_lines"],
        "formula_source_url": formula_result["page_url"],
        "formula_source_label": formula_result["source_label"],
        "formula_is_exact": formula_result["is_exact"],
        "used_gpt": formula_result["used_gpt"],
        "selected_target": formula_result.get("selected_target", {}),
        "final_target": formula_result.get("final_target", {}),
        "formula_chain": formula_result.get("formula_chain", []),
        "input_variables": formula_result.get("input_variables", []),
        "calculation_ready": formula_result.get("calculation_ready", False),
        "reason": formula_result.get("reason", ""),
    }


@app.post("/")
async def submit_form(
    request: Request,
    full_name: str = Form(...),
    group_number: str = Form(...),
    direction: str = Form(...),
    course: str = Form(...),
    current_module: str = Form(...),
):
    direction_code = direction.strip().upper()
    request.session["full_name"] = full_name.strip()
    request.session["group_number"] = group_number.strip()
    request.session["direction"] = direction_code
    request.session["direction_name"] = PROGRAM_BY_CODE.get(direction_code, {}).get("name", direction_code)
    request.session["course"] = course.strip()
    request.session["current_module"] = current_module.strip()
    return RedirectResponse(url="/success", status_code=303)


@app.get("/success")
async def success(request: Request, subject: str | None = None):
    direction_code = request.session.get("direction", "PI")
    course_value = request.session.get("course", "1 курс")
    module_value = request.session.get("current_module", "1 модуль")
    group_number = request.session.get("group_number", "")
    subject_payload = build_subject_payload(direction_code, course_value, module_value)
    subjects = subject_payload["subjects"]
    selected_index, selected_subject = get_selected_subject(subject, subjects)
    selected_subject = enrich_subject_formula(selected_subject, direction_code, module_value)
    selected_subject = enrich_subject_gradebook(selected_subject, direction_code, group_number)

    return templates.TemplateResponse(
        request,
        "success.html",
        {
            "full_name": request.session.get("full_name", "Имя Фамилия"),
            "group_number": group_number,
            "course": course_value,
            "current_module": module_value,
            "direction": request.session.get("direction_name", direction_code),
            "direction_code": direction_code,
            "automats": subject_payload["automats"],
            "subjects": subjects,
            "selected_subject": selected_subject,
            "selected_index": selected_index,
            "preliminary_rank": "12",
            "average_score": "5.4",
            "statement_url": selected_subject["gradebook_url"],
        },
    )


@app.get("/api/profile")
async def profile_api(request: Request, subject: str | None = None):
    direction_code = request.session.get("direction", "PI")
    course_value = request.session.get("course", "1 курс")
    module_value = request.session.get("current_module", "1 модуль")
    group_number = request.session.get("group_number", "")
    subject_payload = build_subject_payload(direction_code, course_value, module_value)
    subjects = subject_payload["subjects"]
    selected_index, selected_subject = get_selected_subject(subject, subjects)
    selected_subject = enrich_subject_formula(selected_subject, direction_code, module_value)
    selected_subject = enrich_subject_gradebook(selected_subject, direction_code, group_number)

    return {
        "full_name": request.session.get("full_name", "Имя Фамилия"),
        "group_number": group_number,
        "direction": request.session.get("direction_name", direction_code),
        "direction_code": direction_code,
        "course": course_value,
        "current_module": module_value,
        "preliminary_rank": "12",
        "average_score": "5.4",
        "automats": subject_payload["automats"],
        "subjects": subjects,
        "selected_index": selected_index,
        "selected_subject": selected_subject,
        "statement_url": selected_subject["gradebook_url"],
    }


@app.get("/api/gradebooks/subject")
async def subject_gradebook_api(
    request: Request,
    subject: str = Query(..., description="Название предмета, например 'English' или 'Calculus 1'"),
    group: str = Query(..., description="Группа в формате 'БПАД 257-1' или '257-1'"),
    program: str | None = Query(None, description="Код программы, например PAD / PI / PMI"),
    academic_year: str = Query(DEFAULT_ACADEMIC_YEAR, description="Учебный год"),
    use_gpt: bool = Query(True, description="Использовать GPT API как fallback для сложных страниц"),
):
    resolved_program = (program or request.session.get("direction", "")).strip() or None

    try:
        result = find_subject_gradebook(
            subject_name=subject,
            group_name=group,
            program_code=resolved_program,
            academic_year=academic_year,
            use_gpt=use_gpt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось получить ведомость из wiki: {exc}") from exc

    if result is None:
        raise HTTPException(status_code=404, detail="Ведомость для этого предмета и группы не найдена")

    return result
