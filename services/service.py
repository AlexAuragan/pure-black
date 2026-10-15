from abc import ABC
from typing import Callable, Generic, TypeVar, cast

T = TypeVar("T")


class Service(ABC, Generic[T]):
    def __init__(self) -> None:
        self._data: T = cast(T, {})
        self._callbacks: list[Callable[[T], None]] = []

    def bind(self, func: Callable[[T], None]) -> None:
        self._callbacks.append(func)

    @property
    def data(self) -> T:
        return self._data
