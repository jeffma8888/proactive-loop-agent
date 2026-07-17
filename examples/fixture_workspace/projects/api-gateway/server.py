"""A minimal request router I keep around as a side project reference.

Stdlib-only on purpose: it's a scratch space for trying routing ideas without
pulling in a framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Route:
    """A method+path bound to a handler returning (status, body)."""

    method: str
    path: str
    handler: Callable[[dict], tuple[int, str]]


class Router:
    """Dispatch (method, path) pairs to registered handlers."""

    def __init__(self) -> None:
        self._routes: list[Route] = []

    def add(self, method: str, path: str, handler: Callable[[dict], tuple[int, str]]) -> None:
        self._routes.append(Route(method.upper(), path, handler))

    def dispatch(self, method: str, path: str, request: dict) -> tuple[int, str]:
        """Return the first matching handler's response, else 404."""
        for route in self._routes:
            if route.method == method.upper() and route.path == path:
                return route.handler(request)
        # TODO: support path parameters (e.g. /items/{id}) instead of exact match.
        return (404, "not found")


def _health(_request: dict) -> tuple[int, str]:
    return (200, "ok")


def build_router() -> Router:
    router = Router()
    router.add("GET", "/health", _health)
    return router


if __name__ == "__main__":
    print(build_router().dispatch("GET", "/health", {}))
