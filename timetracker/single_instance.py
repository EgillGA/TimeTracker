"""One window at a time, using a named Windows mutex.

A mutex rather than a PID file on purpose: Windows releases it when the
process ends however it ends, so a crash cannot leave a stale lock that
suppresses tomorrow's prompt. A PID file would need liveness checks that are
awkward and unreliable on Windows.

Failing to take the lock is never fatal. A duplicate window is a nuisance; no
window at all defeats the point of the tool.
"""

import ctypes

ERROR_ALREADY_EXISTS = 183
DEFAULT_NAME = "TimeTracker-SingleInstance"


class SingleInstance:
    def __init__(self, name=DEFAULT_NAME):
        # "Local\" scopes the name to this logon session, which is the right
        # boundary: two different users on one machine each get their own.
        self.name = f"Local\\{name}"
        self.acquired = False
        self._handle = None

    def acquire(self):
        """Claim the name. True if this process now owns it."""
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.CreateMutexW(None, False, self.name)
            already_running = kernel32.GetLastError() == ERROR_ALREADY_EXISTS
        except (AttributeError, OSError):
            # Not Windows, or the call is unavailable. Let the window open.
            self.acquired = True
            return True

        self._handle = handle
        self.acquired = not already_running
        if already_running:
            self.release()
        return self.acquired

    def release(self):
        if self._handle is None:
            return
        try:
            ctypes.windll.kernel32.CloseHandle(self._handle)
        except (AttributeError, OSError):
            pass
        self._handle = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_exc):
        self.release()
        return False
