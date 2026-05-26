"""
Global skip controller.
A background thread watches stdin. Typing 's' + Enter at any point
during an application signals all apply loops to abort immediately.
"""

import sys
import threading


class SkipController:
    def __init__(self):
        self._skip = threading.Event()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        """Start the background stdin watcher (call once at pipeline start)."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def reset(self):
        """Clear skip flag between jobs."""
        self._skip.clear()

    def requested(self) -> bool:
        return self._skip.is_set()

    def _watch(self):
        while self._running:
            try:
                line = sys.stdin.readline()
                if line.strip().lower() == "s":
                    self._skip.set()
                    print("\n  [SKIP] Skip requested — aborting current application...", flush=True)
            except Exception:
                break


# Singleton — imported everywhere
skipper = SkipController()
