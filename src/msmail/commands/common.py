"""Shared CLI operation helpers."""
from typing import Callable, Iterable, TypeVar

from msmail.core.errors import MsmailError

T = TypeVar("T")
R = TypeVar("R")


def run_batch(items: Iterable[T], action: Callable[[T], R], *, identify: Callable[[T], str]) -> list[R]:
    results = []
    completed = []
    for item in items:
        try:
            results.append(action(item))
        except (MsmailError, OSError, ValueError) as exc:
            progress = ", ".join(completed) or "none"
            raise MsmailError(
                f"Operation failed for {identify(item)}: {exc}. "
                f"Completed IDs: {progress}. Remaining items were not attempted."
            ) from exc
        completed.append(identify(item))
    return results
