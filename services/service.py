from abc import ABC, abstractmethod
from typing import Any, Callable, Generic, TypeVar


T = TypeVar("T")

class Service(ABC, Generic[T]):
    def __init__(self):
        # the keys are the monitor ids, each data is here once per monitor
        self._data: dict[int | str, T] = {}
        self._callbacks: list[Callable[[dict[int | str, T]], None]] = []

    def bind(self, func: Callable[[dict[int | str, T]], None]):
        self._callbacks.append(func)

    @property
    def data(self):
        return self._data