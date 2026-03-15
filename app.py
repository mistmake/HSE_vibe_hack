from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware


app = FastAPI(title="HSE Vibe Hack")
app.add_middleware(SessionMiddleware, secret_key="hackathon-demo-secret")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


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
    {"name": "Программирование", "local_rank": "56/220", "score": "4.5"},
    {"name": "Математический анализ", "local_rank": "41/220", "score": "5.2"},
    {"name": "Дискретная математика", "local_rank": "63/220", "score": "4.8"},
    {"name": "Английский язык", "local_rank": "34/220", "score": "5.4"},
]


def get_selected_subject(subject: str | None):
    try:
        selected_index = int(subject or "1") - 1
    except ValueError:
        selected_index = 0

    if selected_index < 0 or selected_index >= len(SUBJECTS):
        selected_index = 0

    return selected_index, SUBJECTS[selected_index]


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
