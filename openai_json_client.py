from __future__ import annotations

import json
import os
import urllib.request


OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4.1-mini"


def has_openai_api_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def call_openai_json(
    *,
    system_prompt: str,
    user_payload: dict,
    model: str | None = None,
    temperature: float = 0,
) -> dict:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY не найден. Задай ключ через переменную окружения.")

    payload = {
        "model": model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
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

    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)

    content = data["choices"][0]["message"]["content"]
    return json.loads(content)
