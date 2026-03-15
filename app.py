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

from gradebook_finder import DEFAULT_ACADEMIC_YEAR, find_subject_gradebook


app = FastAPI(title="HSE Vibe Hack")
app.add_middleware(SessionMiddleware, secret_key="hackathon-demo-secret")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


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

FORMULA_PRESETS = [
    "0.4 × контрольные + 0.3 × домашние задания + 0.3 × экзамен",
    "0.5 × накопленная оценка + 0.5 × экзамен",
    "0.35 × практические задания + 0.25 × квизы + 0.4 × экзамен",
    "0.3 × лабораторные работы + 0.3 × проект + 0.4 × экзамен",
    "0.4 × семинары + 0.2 × самостоятельная работа + 0.4 × экзамен",
    "0.6 × накопленная оценка + 0.4 × экзамен",
]


def normalize_text(value: str) -> str:
    return value.lower().replace("ё", "е")


def build_formula_info(name: str, index: int, module_value: str) -> dict:
    lower_name = normalize_text(name)
    module_number = parse_module_number(module_value)
    late_module = module_number >= 3

    exact_rules = [
        {
            "patterns": ("введение в программную инженерию",),
            "formula": "0.4 * Домашнее задание (ДЗ1) + 0.2 * Домашнее задание (ДЗ2) + 0.4 * Экзамен (Экз)",
            "source_url": "https://www.hse.ru/edu/courses/1048869220",
        },
        {
            "patterns": ("алгебра",),
            "formula": (
                "О2 = 0,5·Онакопл + 0,2·Оауд.раб. + 0,3·Оэкз, где Онакопл = 0,35·Ок/р2 + 0,25·Од/з3 + 0,4·Од/з4 + Экз.раб.-1"
                if late_module
                else "О1 = 0,4·Онакопл + 0,4·Окр1 + 0,2·Оэкз, где Онакопл = 0,35·Ок/р1 + 0,25·Од/з1 + 0,4·Од/з2"
            ),
            "source_url": "https://www.hse.ru/edu/courses/992431400",
        },
        {
            "patterns": ("математический анализ",),
            "formula": (
                "О2 = 0,7·Онакопл + 0,3·Оэкз, где Онакопл = 0,4·Ок/р1 + 0,6·Ок/р2"
                if late_module
                else "О1 = 0,7·Онакопл + 0,3·Оэкз, где Онакопл = 0,6·Одз + 0,4·Ок/р"
            ),
            "source_url": "https://www.hse.ru/edu/courses/499689014",
        },
        {
            "patterns": ("дискретная математика",),
            "formula": (
                "Оценка в промежуточном контроле за четвертый модуль = 0.2* оценка за самостоятельную работу + 0.3* оценка за контрольную работу + 0.5* оценка за экзамен"
                if late_module
                else "Оценка в промежуточном контроле за второй модуль = 0.3* оценка за самостоятельную работу + 0.3* оценка за контрольную работу + 0.4* оценка за экзамен"
            ),
            "source_url": "https://www.hse.ru/edu/courses/920918968",
        },
        {
            "patterns": ("история россии", "russian history"),
            "formula": "0,4* работа на семинарских занятиях + 0,6*письменный экзамен",
            "source_url": "https://www.hse.ru/edu/courses/981310937",
        },
        {
            "patterns": ("линейная алгебра и геометрия", "linear algebra"),
            "formula": "F = 0,2·Q1 + 0,2·Q2 + 0,2·Q3 + 0,4·Exam, где Q1-Q3 - оценки за контрольные мероприятия, а Exam - оценка за экзамен",
            "source_url": "https://www.hse.ru/edu/courses/923275839",
        },
        {
            "patterns": ("архитектура компьютера и операционные системы",),
            "formula": "0.05 * Активность на семинарах + 0.05 * Активность на семинарах + 0.3 * Домашнее задание + 0.3 * Домашнее задание + 0.1 * Контрольная работа + 0.1 * Контрольная работа + 0.1 * Экзамен",
            "source_url": "https://www.hse.ru/edu/courses/1048863976",
        },
        {
            "patterns": ("алгоритмы и структуры данных", "algorithms and data structures"),
            "formula": "0.3 * Экзамен + 0.4 * Большие домашние задания + 0.2 * Маленькие домашние задания + 0.1 * Контрольная работа",
            "source_url": "https://www.hse.ru/edu/courses/1048856505",
        },
        {
            "patterns": ("основы программирования на c++", "язык программирования c++"),
            "formula": "Мин(Округление(0.6 * Большие_дз + 0.4 * Маленькие_дз + Б), 10), где Б — бонус",
            "source_url": "https://www.hse.ru/edu/courses/1014898936",
        },
        {
            "patterns": ("python programming language (advanced course)",),
            "formula": "0.4*task1 + 0.4*task2 + 0.2*classwork",
            "source_url": "https://www.hse.ru/edu/courses/759625360",
        },
        {
            "patterns": ("machine learning 1",),
            "formula": "0.1 * hw + 0.4 * contest + 0.5 * exam",
            "source_url": "https://www.hse.ru/edu/courses/758248162",
        },
        {
            "patterns": ("mathematical statistics",),
            "formula": "Midterm Assessment = 0.2 * Homework + 0.4 * Test + 0.4 * Exam",
            "source_url": "https://www.hse.ru/edu/courses/759794992",
        },
        {
            "patterns": ("теория вероятностей", "probability theory"),
            "formula": (
                "The course grade for the 4th module is 0.6 * FinalExam + 0.2 * SpringMock (April Midterm) + 0.2 * spring Home assignments."
                if late_module
                else "The course grade for the 1st module is 0.7 * FallMock (October Midterm) + 0.3 * fall Home assignments."
            ),
            "source_url": "https://www.hse.ru/edu/courses/758318906",
        },
    ]

    for rule in exact_rules:
        if any(pattern in lower_name for pattern in rule["patterns"]):
            return {
                "formula": rule["formula"],
                "source_url": rule["source_url"],
                "source_label": "Официальная страница курса ВШЭ",
                "is_exact": True,
            }

    fallback_formula = FORMULA_PRESETS[index % len(FORMULA_PRESETS)]
    return {
        "formula": fallback_formula,
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

    return [make_subject(name, index, module_value) for index, name in enumerate(unique_names[:8])]


def get_selected_subject(subject: str | None, subjects: list[dict]):
    try:
        selected_index = int(subject or "1") - 1
    except ValueError:
        selected_index = 0

    if selected_index < 0 or selected_index >= len(subjects):
        selected_index = 0

    return selected_index, subjects[selected_index]


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
    subject_payload = build_subject_payload(direction_code, course_value, module_value)
    subjects = subject_payload["subjects"]
    selected_index, selected_subject = get_selected_subject(subject, subjects)

    return templates.TemplateResponse(
        request,
        "success.html",
        {
            "full_name": request.session.get("full_name", "Имя Фамилия"),
            "group_number": request.session.get("group_number", ""),
            "course": course_value,
            "current_module": module_value,
            "direction": request.session.get("direction_name", direction_code),
            "automats": subject_payload["automats"],
            "subjects": subjects,
            "selected_subject": selected_subject,
            "selected_index": selected_index,
            "preliminary_rank": "12",
            "average_score": "5.4",
        },
    )


@app.get("/api/profile")
async def profile_api(request: Request, subject: str | None = None):
    direction_code = request.session.get("direction", "PI")
    course_value = request.session.get("course", "1 курс")
    module_value = request.session.get("current_module", "1 модуль")
    subject_payload = build_subject_payload(direction_code, course_value, module_value)
    subjects = subject_payload["subjects"]
    selected_index, selected_subject = get_selected_subject(subject, subjects)

    return {
        "full_name": request.session.get("full_name", "Имя Фамилия"),
        "group_number": request.session.get("group_number", ""),
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
