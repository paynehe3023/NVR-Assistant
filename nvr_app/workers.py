from __future__ import annotations

import threading
from typing import Any, Callable, Iterable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class TaskSignals(QObject):
    progress = Signal(dict)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class ServiceTask(QRunnable):
    """Run a blocking service call without touching the GUI thread."""

    def __init__(
        self,
        function: Callable[..., Any],
        *args: Any,
        cancel_exceptions: Iterable[type[Exception]] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._function = function
        self._args = args
        self._kwargs = kwargs
        self._cancel_exceptions = tuple(cancel_exceptions)
        self._cancel_event = threading.Event()
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            result = self._function(
                *self._args,
                progress=self.signals.progress.emit,
                cancel_event=self._cancel_event,
                **self._kwargs,
            )
        except Exception as exc:
            if any(isinstance(exc, item) for item in self._cancel_exceptions):
                self.signals.cancelled.emit()
                return
            self.signals.failed.emit(str(exc))
            return

        if self._cancel_event.is_set():
            self.signals.cancelled.emit()
        else:
            self.signals.finished.emit(result)

