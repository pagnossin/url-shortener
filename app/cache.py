import threading
import time
from collections import OrderedDict
from collections.abc import Callable


class TTLCache[V]:
    def __init__(self, max_entries: int, clock: Callable[[], float] = time.monotonic):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()  # sync endpoints run in a threadpool
        self._entries: OrderedDict[str, tuple[float, V]] = OrderedDict()

    def get(self, key: str) -> V | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            deadline, value = entry
            if self._clock() >= deadline:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return value

    def put(self, key: str, value: V, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        with self._lock:
            self._entries[key] = (self._clock() + ttl_seconds, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
