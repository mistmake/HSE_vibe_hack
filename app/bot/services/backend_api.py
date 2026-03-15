from __future__ import annotations

from typing import Any


class BackendClient:
    """Future HTTP adapter placeholder.

    The Telegram handlers should talk to service interfaces, not call this client directly.
    This class exists as a stable seam for a later FastAPI integration.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError("Remote backend is not connected yet.")
