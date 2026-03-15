import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware


app = FastAPI(title="HSE Vibe Hack")
app.add_middleware(SessionMiddleware, secret_key="hackathon-demo-secret")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

WIKI_BASE_URL = "http://wiki.cs.hse.ru"
DEFAULT_ACADEMIC_YEAR = "2025/2026"
WIKI_DIRECTION_ALIASES = {
    "аналитика": "DSBA",
    "business analytics": "DSBA",
    "data science and business analytics": "DSBA",
    "dsba": "DSBA",
}


DIRECTIONS = [
    "Программная инженерия",
    "Дизайн",
    "Аналитика",
    "Маркетинг",
    "Менеджмент",
]

COURSES = ["1 курс", "2 курс", "3 курс", "4 курс"]

MODULES = ["1 модуль", "2 модуль", "3 модуль", "4 модуль"]

AUTOMATS = [
    "Высшая математика",
    "Алгоритмы и структуры данных",
    "Академическое письмо",
    "Английский язык",
]

SUBJECTS = [
    {
        "slug": "programming",
        "name": "Программирование",
        "aliases": ["programming"],
        "local_rank": "56/220",
        "score": "4.5",
        "direction": "Программная инженерия",
        "course": 1,
        "grading_text": """
        CUM1 = 0.4*Lab1 + 0.3*Lab2 + 0.3*Quiz1
        G1 = 0.6*CUM1 + 0.4*Exam1
        """,
    },
    {
        "slug": "calculus-1",
        "name": "Математический анализ",
        "aliases": ["calculus 1", "calculous 1", "math analysis", "математический анализ"],
        "local_rank": "41/220",
        "score": "5.2",
        "direction": "Программная инженерия",
        "course": 1,
        "grading_text": """
        CUM2 = 0.15*CW3 + 0.25*Mid2 + 0.15*CW4 + 0.25*Colloq2 + 0.2*Q2 (no rounding)
        G2 = 0.7*CUM2 + 0.3*Exam2 + Bonus2 (no rounding)

        Mid2 - Written control work (midterm) at the end of the 3rd
        module (or at the beginning of the 4th module)
        Exam2 - Written exam at the end of the 4th module
        Bonus2 - Number of bonus points for bonus tasks
        """,
    },
    {
        "slug": "discrete-math",
        "name": "Дискретная математика",
        "aliases": ["discrete math", "дискретная математика"],
        "local_rank": "63/220",
        "score": "4.8",
        "direction": "Программная инженерия",
        "course": 1,
        "grading_text": """
        CUM1 = 0.25*HW1 + 0.25*HW2 + 0.5*Test1
        G1 = 0.7*CUM1 + 0.3*Exam1
        """,
    },
    {
        "slug": "english",
        "name": "Английский язык",
        "aliases": ["english", "английский язык"],
        "local_rank": "34/220",
        "score": "5.4",
        "direction": "Программная инженерия",
        "course": 1,
        "grading_text": """
        CUM1 = 0.5*Speaking + 0.3*Writing + 0.2*Quiz
        G1 = 0.8*CUM1 + 0.2*Exam1
        """,
    },
]


def get_selected_subject(subject: str | None):
    try:
        selected_index = int(subject or "1") - 1
    except ValueError:
        selected_index = 0

    if selected_index < 0 or selected_index >= len(SUBJECTS):
        selected_index = 0

    return selected_index, SUBJECTS[selected_index]


def normalize_subject_key(value: str) -> str:
    return re.sub(r"[^a-zA-Zа-яА-Я0-9]+", "-", value.strip().lower()).strip("-")


def find_subject_by_name(subject: str):
    lookup = normalize_subject_key(subject)

    for item in SUBJECTS:
        candidates = [item["slug"], item["name"], *item.get("aliases", [])]
        normalized_candidates = {normalize_subject_key(candidate) for candidate in candidates}

        if lookup in normalized_candidates:
            return item

    return None


def extract_formula_lines(grading_text: str, module: int) -> list[str]:
    formulas = []

    for raw_line in grading_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        compact_line = re.sub(r"\s+", "", line).upper()
        if compact_line.startswith((f"CUM{module}=", f"CUM_{module}=", f"G{module}=", f"G_{module}=")):
            formulas.append(line)

    return formulas


def normalize_direction_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def resolve_wiki_direction(direction: str | None) -> str:
    if not direction:
        raise HTTPException(status_code=400, detail="Не передано направление")

    direction_key = normalize_direction_key(direction)
    if direction_key in WIKI_DIRECTION_ALIASES:
        return WIKI_DIRECTION_ALIASES[direction_key]

    raw_value = direction.strip().upper()
    if re.fullmatch(r"[A-Z]{2,10}", raw_value):
        return raw_value

    raise HTTPException(status_code=400, detail="Для направления пока нет сопоставления с wiki")


def wiki_api_url(params: dict[str, str]) -> str:
    return f"{WIKI_BASE_URL}/api.php?{urllib.parse.urlencode(params)}"


@lru_cache(maxsize=64)
def fetch_json(url: str) -> dict:
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            time.sleep(0.25 * (attempt + 1))

    raise last_error


@lru_cache(maxsize=256)
def fetch_wiki_raw(title: str) -> str:
    raw_url = f"{WIKI_BASE_URL}/index.php?{urllib.parse.urlencode({'title': title, 'action': 'raw'})}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(raw_url, timeout=20) as response:
                return response.read().decode("utf-8", errors="ignore")
        except Exception:
            time.sleep(0.25 * (attempt + 1))

    return ""


@lru_cache(maxsize=32)
def fetch_direction_titles(wiki_direction: str, academic_year: str) -> list[str]:
    params = {
        "action": "query",
        "list": "allpages",
        "aplimit": "500",
        "format": "json",
    }
    apfrom = None
    matched_titles = []
    needle = f" {wiki_direction} {academic_year}"

    for _ in range(100):
        current_params = params.copy()
        if apfrom:
            current_params["apfrom"] = apfrom

        data = fetch_json(wiki_api_url(current_params))
        pages = data.get("query", {}).get("allpages", [])
        matched_titles.extend(
            page["title"] for page in pages if needle in page.get("title", "")
        )

        apfrom = data.get("query-continue", {}).get("allpages", {}).get("apfrom")
        if not apfrom:
            break

    return matched_titles


def extract_modules_from_title(title: str) -> list[int]:
    match = re.search(r"modules\s+([1-4])\s*-\s*([1-4])$", title, flags=re.IGNORECASE)
    if not match:
        return []

    start_module = int(match.group(1))
    end_module = int(match.group(2))
    if start_module > end_module:
        start_module, end_module = end_module, start_module

    return list(range(start_module, end_module + 1))


def extract_modules_from_raw(raw_text: str) -> list[int]:
    semester_1_patterns = (
        r"CUM\s*<sub>\s*1\s*</sub>",
        r"G\s*<sub>\s*1\s*</sub>",
        r"Final\s*<sub>\s*1\s*</sub>",
        r"Exam\s*<sub>\s*1\s*</sub>",
        r"CUM1\b",
        r"G1\b",
        r"Exam1\b",
    )
    semester_2_patterns = (
        r"CUM\s*<sub>\s*2\s*</sub>",
        r"G\s*<sub>\s*2\s*</sub>",
        r"Final\s*<sub>\s*2\s*</sub>",
        r"Exam\s*<sub>\s*2\s*</sub>",
        r"CUM2\b",
        r"G2\b",
        r"Exam2\b",
        r"CW\s*<sub>\s*3\s*</sub>",
        r"CW\s*<sub>\s*4\s*</sub>",
    )

    modules = set()
    if any(re.search(pattern, raw_text, flags=re.IGNORECASE) for pattern in semester_1_patterns):
        modules.update({1, 2})
    if any(re.search(pattern, raw_text, flags=re.IGNORECASE) for pattern in semester_2_patterns):
        modules.update({3, 4})

    for module in re.findall(r"\bM([1-4])\b", raw_text, flags=re.IGNORECASE):
        modules.add(int(module))

    for module in re.findall(r"\b(?:module|mod)\s*([1-4])\b", raw_text, flags=re.IGNORECASE):
        modules.add(int(module))

    for module in re.findall(r"\b([1-4])(?:st|nd|rd|th)\s+module\b", raw_text, flags=re.IGNORECASE):
        modules.add(int(module))

    if re.search(r"\b(?:1st|first)\s+semester\b", raw_text, flags=re.IGNORECASE):
        modules.update({1, 2})
    if re.search(r"\b(?:2nd|second)\s+semester\b", raw_text, flags=re.IGNORECASE):
        modules.update({3, 4})

    return sorted(modules)


def build_subject_entry(title: str, wiki_direction: str, academic_year: str) -> dict:
    base_title = re.sub(rf"\s+{re.escape(wiki_direction)}\s+{re.escape(academic_year)}.*$", "", title).strip()
    modules = extract_modules_from_title(title)
    if not modules:
        modules = extract_modules_from_raw(fetch_wiki_raw(title))

    return {
        "base_title": base_title,
        "page_title": title,
        "modules": modules,
    }


@lru_cache(maxsize=16)
def build_direction_summary(wiki_direction: str, academic_year: str) -> dict:
    titles = fetch_direction_titles(wiki_direction, academic_year)
    if not titles:
        return {
            "academic_year": academic_year,
            "subjects_total": 0,
            "module_counts": {str(module): 0 for module in range(1, 5)},
            "semester_counts": {"1": 0, "2": 0, "full_year": 0, "unknown": 0},
            "subjects": [],
        }

    subject_entries = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_map = {
            pool.submit(build_subject_entry, title, wiki_direction, academic_year): title for title in titles
        }
        for future in as_completed(future_map):
            subject_entries.append(future.result())

    grouped_subjects = {}
    for entry in subject_entries:
        base_title = entry["base_title"]
        grouped_subjects.setdefault(
            base_title,
            {"name": base_title, "pages": [], "modules": set()},
        )
        grouped_subjects[base_title]["pages"].append(entry["page_title"])
        grouped_subjects[base_title]["modules"].update(entry["modules"])

    module_counts = {str(module): 0 for module in range(1, 5)}
    semester_counts = {"1": 0, "2": 0, "full_year": 0, "unknown": 0}
    subjects = []

    for base_title in sorted(grouped_subjects):
        subject = grouped_subjects[base_title]
        modules = sorted(subject["modules"])
        for module in modules:
            module_counts[str(module)] += 1

        if modules == [1, 2, 3, 4]:
            semester_counts["full_year"] += 1
        elif modules and set(modules).issubset({1, 2}):
            semester_counts["1"] += 1
        elif modules and set(modules).issubset({3, 4}):
            semester_counts["2"] += 1
        else:
            semester_counts["unknown"] += 1

        subjects.append(
            {
                "name": subject["name"],
                "modules": modules,
                "pages": sorted(subject["pages"]),
            }
        )

    return {
        "academic_year": academic_year,
        "subjects_total": len(subjects),
        "module_counts": module_counts,
        "semester_counts": semester_counts,
        "subjects": subjects,
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
            "directions": DIRECTIONS,
            "courses": COURSES,
            "modules": MODULES,
        },
    )


@app.post("/")
async def submit_form(
    request: Request,
    full_name: str = Form(...),
    group_number: str = Form(...),
    direction: str = Form(...),
    course: str = Form(...),
    current_module: str = Form(...),
):
    request.session["full_name"] = full_name.strip()
    request.session["group_number"] = group_number.strip()
    request.session["direction"] = direction.strip()
    request.session["course"] = course.strip()
    request.session["current_module"] = current_module.strip()
    return RedirectResponse(url="/success", status_code=303)


@app.get("/success")
async def success(request: Request, subject: str | None = None):
    selected_index, selected_subject = get_selected_subject(subject)

    return templates.TemplateResponse(
        request,
        "success.html",
        {
            "full_name": request.session.get("full_name", "Имя Фамилия"),
            "automats": AUTOMATS,
            "subjects": SUBJECTS,
            "selected_subject": selected_subject,
            "selected_index": selected_index,
            "preliminary_rank": "12",
            "average_score": "5.4",
        },
    )


@app.get("/api/profile")
async def profile_api(request: Request, subject: str | None = None):
    selected_index, selected_subject = get_selected_subject(subject)

    return {
        "full_name": request.session.get("full_name", "Имя Фамилия"),
        "group_number": request.session.get("group_number", ""),
        "direction": request.session.get("direction", ""),
        "course": request.session.get("course", ""),
        "current_module": request.session.get("current_module", ""),
        "preliminary_rank": "12",
        "average_score": "5.4",
        "automats": AUTOMATS,
        "subjects": SUBJECTS,
        "selected_index": selected_index,
        "selected_subject": selected_subject,
    }


@app.get("/api/subjects/formula")
async def subject_formula_api(
    subject: str = Query(..., description="Название или slug предмета"),
    module: int = Query(..., ge=1, le=4, description="Номер текущего модуля"),
    direction: str | None = Query(None, description="Направление"),
    course: int | None = Query(None, ge=1, le=6, description="Курс"),
):
    subject_data = find_subject_by_name(subject)
    if subject_data is None:
        raise HTTPException(status_code=404, detail="Предмет не найден")

    if direction and subject_data.get("direction") != direction:
        raise HTTPException(status_code=404, detail="Предмет не найден для выбранного направления")

    if course and subject_data.get("course") != course:
        raise HTTPException(status_code=404, detail="Предмет не найден для выбранного курса")

    formula_lines = extract_formula_lines(subject_data.get("grading_text", ""), module)
    if not formula_lines:
        raise HTTPException(status_code=404, detail="Формула для выбранного модуля не найдена")

    return {
        "subject": subject_data["name"],
        "module": module,
        "formula": "\n".join(formula_lines),
        "formula_lines": formula_lines,
    }


@app.get("/api/curriculum/subjects-count")
async def curriculum_subjects_count_api(
    request: Request,
    direction: str | None = Query(None, description="Направление из формы или wiki-код вроде DSBA"),
    academic_year: str = Query(DEFAULT_ACADEMIC_YEAR, description="Учебный год"),
    module: int | None = Query(None, ge=1, le=4, description="Если нужен счетчик для конкретного модуля"),
):
    selected_direction = (direction or request.session.get("direction", "")).strip()
    wiki_direction = resolve_wiki_direction(selected_direction)

    try:
        summary = build_direction_summary(wiki_direction, academic_year)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось получить данные с wiki: {exc}") from exc

    response = {
        "direction": selected_direction or wiki_direction,
        "wiki_direction": wiki_direction,
        **summary,
    }

    if module is not None:
        response["subjects_in_module"] = summary["module_counts"][str(module)]
        response["requested_module"] = module

    return response
