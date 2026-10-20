"""Single-process provider-header pacing; no network calls or quota probes."""
from email.utils import parsedate_to_datetime
import math

class MinuteQuota:
    def __init__(self):
        self.left = None
        self.reset_at = None
        self.window = None
        self.attempts = 0

    def delay(self, monotonic):
        if self.reset_at is not None and monotonic >= self.reset_at:
            self.left = None
            self.reset_at = None
            self.window = monotonic
            self.attempts = 0
        if self.left is not None:
            return max(0.0, self.reset_at - monotonic) if self.left == 0 else 0.0
        if self.window is None:
            return 0.0
        return max(0.0, 65.0 - (monotonic - self.window)) if self.attempts >= 6 else 0.0

    def reserve(self, monotonic):
        if self.delay(monotonic) > 0:
            raise RuntimeError("quota wait required")
        if self.window is None or monotonic - self.window >= 65:
            self.window = monotonic
            self.attempts = 0
        self.attempts += 1
        if self.left is not None:
            self.left -= 1

    def observe(self, headers, wall, monotonic):
        # Clear old evidence when the new response has no usable quota headers.
        try:
            used = int(headers["api-credits-used"])
            left = int(headers["api-credits-left"])
            if used < 0 or left < 0 or used + left != 8:
                raise ValueError("invalid Basic quota")
        except (KeyError, ValueError, TypeError):
            self.left = None
            self.reset_at = None
            return
        self.left = left
        try:
            server = parsedate_to_datetime(headers["Date"]).timestamp()
            if not math.isfinite(server):
                raise ValueError("invalid server clock")
            # Date is second-resolution; one-second margin prevents early reset.
            wait = 60 - server % 60 + 1
        except (KeyError, ValueError, TypeError, OverflowError):
            # No response clock evidence: retain the conservative 65s fallback.
            wait = 65
        self.reset_at = monotonic + wait
