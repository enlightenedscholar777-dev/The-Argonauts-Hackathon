import time
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).timestamp()


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


class SessionClock:
    def __init__(self, scenario_time):
        self.anchor = scenario_time
        self.monotonic = time.monotonic()

    def now(self):
        return self.anchor + time.monotonic() - self.monotonic
