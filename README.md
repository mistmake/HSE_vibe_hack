# HSE_vibe_hack

Проект переписан на `FastAPI`.

## Что есть сейчас

- HTML-страницы через шаблоны
- статика в папке `static`
- форма на главной странице
- отдельная вторая страница после сохранения
- API-эндпоинт: `/api/profile`
- API-эндпоинт с формулой оценивания: `/api/subjects/formula`
- API-эндпоинт с количеством предметов по направлению из wiki: `/api/curriculum/subjects-count`

## Как установить

Открой терминал в папке проекта и выполни:

```powershell
pip install -r requirements.txt
```

## Как запустить

```powershell
uvicorn app:app --reload
```

После запуска открой:

- `http://127.0.0.1:8000`

## Полезные адреса

- главная страница: `http://127.0.0.1:8000`
- вторая страница: `http://127.0.0.1:8000/success`
- API: `http://127.0.0.1:8000/api/profile`
- формула оценивания: `http://127.0.0.1:8000/api/subjects/formula?subject=calculus-1&module=2`
- предметы по направлению: `http://127.0.0.1:8000/api/curriculum/subjects-count?direction=DSBA&academic_year=2025/2026&module=3`
- swagger-документация FastAPI: `http://127.0.0.1:8000/docs`
