from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable

ProgressCb = Callable[[float, str], None]     # (fraction 0..1, log line)

class Cancelled(Exception): ...

class Executor(ABC):
    name: str
    @abstractmethod
    def health(self) -> dict: ...
    @abstractmethod
    def run(self, spec: dict, workdir: str, on_progress: ProgressCb, is_cancelled: Callable[[], bool]) -> dict:
        """Run a RenderSpec (dict) and return the engine result dict (wav path etc.)."""
