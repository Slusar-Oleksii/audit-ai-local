from __future__ import annotations

from contextlib import contextmanager
from threading import Lock, RLock
from typing import Iterator


_registry_guard = Lock()
_project_locks: dict[str, RLock] = {}


@contextmanager
def project_lock(project_id: str) -> Iterator[None]:
    """Серіалізує індексацію, аудит і видалення одного проєкту в межах процесу."""

    with _registry_guard:
        lock = _project_locks.setdefault(project_id, RLock())
    with lock:
        yield
