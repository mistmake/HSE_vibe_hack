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
- API-эндпоинт с ведомостью по предмету и группе: `/api/gradebooks/subject`
- отдельный скрипт поиска ведомостей по группе: `gradebook_finder.py`

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
- ведомость по предмету: `http://127.0.0.1:8000/api/gradebooks/subject?subject=English&group=%D0%91%D0%9F%D0%90%D0%94%20257-1&program=PAD&use_gpt=false`
- swagger-документация FastAPI: `http://127.0.0.1:8000/docs`

## Скрипт ведомостей

Поиск ссылок на ведомости по программе и группе:

```powershell
python3 gradebook_finder.py --program PAD --group "БПАД 257-1" --no-gpt
```

Поиск сразу для всех групп программы:

```powershell
python3 gradebook_finder.py --program PAD --all-groups --no-gpt
```

Если хочешь подключить GPT API для более умного выбора ссылки на сложных страницах:

```powershell
set OPENAI_API_KEY=your_key
set OPENAI_MODEL=gpt-4.1-mini
python3 gradebook_finder.py --program PAD --group "БПАД 257-1"
```
