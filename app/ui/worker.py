import asyncio
import threading
from PySide6.QtCore import QThread, Signal


class AsyncWorker(QThread):
    result = Signal(object)
    status = Signal(str, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.loop = None
        self.task = None
        self.cancelled = threading.Event()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        async def execute():
            if self.cancelled.is_set():
                return
            return await self.operation(self.result.emit, self.status.emit)
        self.task = self.loop.create_task(execute())
        def check_cancel():
            if self.task.done():
                return
            if self.cancelled.is_set():
                self.task.cancel()
            else:
                self.loop.call_later(0.1, check_cancel)
        # Polling also works in sandboxes where the asyncio self-pipe cannot wake a selector.
        self.loop.call_later(0.1, check_cancel)
        try:
            result = self.loop.run_until_complete(self.task)
            self.completed.emit(result)
        except asyncio.CancelledError:
            self.status.emit('Research', 'Cancelled; partial results retained')
        except Exception as exc:
            # Never emit request objects, URLs with query credentials, or response payloads.
            self.failed.emit('Operation failed: ' + type(exc).__name__)
        finally:
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    def cancel(self):
        self.cancelled.set()
        if self.loop and self.task and not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass
