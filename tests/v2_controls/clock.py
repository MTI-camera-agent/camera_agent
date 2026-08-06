"""A virtual monotonic clock for deterministic v2 replay.

Every duration in the replay harness uses one owner's monotonic clock
(``docs/CAMERA_AGENT_V2_EVALUATION.md`` §7). Tests MUST NOT call
``time.monotonic()`` directly; they drive time through this clock so heartbeat
backoff, Settled dwell, Reasoner deadlines, and capture/edit deadlines advance
deterministically and in declared order.

The clock is deterministic and side-effect free: it never reads wall time and
never sleeps. ``advance`` fires scheduled timers in (absolute-time, insertion)
order and returns the fired timers so a test can assert exactly which deadlines
matured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class ScheduledTimer:
    """One scheduled virtual-time callback.

    ``fire_at`` is absolute virtual seconds. Insertion order breaks ties so two
    timers due at the same instant mature in the order they were scheduled.
    """

    timer_id: int
    fire_at: float
    label: str
    callback: Callable[[], None]

    def __post_init__(self) -> None:
        if self.timer_id < 0:
            raise ValueError("timer id must not be negative")


class VirtualMonotonicClock:
    """A deterministic virtual monotonic clock.

    The clock starts at ``0.0`` (or a configured origin) and advances only when a
    test calls ``advance``. It owns a monotonically increasing timer-id space so
    timer insertion order is stable and reproducible across runs.
    """

    def __init__(self, origin: float = 0.0) -> None:
        if origin < 0.0:
            raise ValueError("clock origin must not be negative")
        self._now = origin
        self._next_timer_id = 0
        self._timers: list[ScheduledTimer] = []

    def now(self) -> float:
        """Return the current virtual monotonic seconds."""
        return self._now

    def advance(self, seconds: float) -> list[ScheduledTimer]:
        """Advance virtual time and fire every timer that came due.

        Timers due at the same instant fire in insertion order. Returns the fired
        timers in the order they ran so a test can assert deadline maturation.
        Negative or zero advances are no-ops that fire nothing.
        """
        if seconds < 0.0:
            raise ValueError("virtual time must not move backwards")
        if seconds == 0.0:
            return []
        target = self._now + seconds
        due = sorted(
            [t for t in self._timers if t.fire_at <= target],
            key=lambda t: (t.fire_at, t.timer_id),
        )
        self._timers = [t for t in self._timers if t.fire_at > target]
        self._now = target
        for timer in due:
            timer.callback()
        return due

    def schedule(self, at: float, callback: Callable[[], None], *, label: str = "") -> ScheduledTimer:
        """Schedule a callback at an absolute virtual time.

        Returns the scheduled timer so a test can cancel or inspect it. Timers
        scheduled in the past are still fired on the next ``advance`` (including a
        zero-second advance that explicitly drains them).
        """
        timer = ScheduledTimer(
            timer_id=self._next_timer_id,
            fire_at=at,
            label=label,
            callback=callback,
        )
        self._next_timer_id += 1
        self._timers.append(timer)
        return timer

    def schedule_relative(
        self, delay: float, callback: Callable[[], None], *, label: str = ""
    ) -> ScheduledTimer:
        if delay < 0.0:
            raise ValueError("relative timer delay must not be negative")
        return self.schedule(self._now + delay, callback, label=label)

    def cancel(self, timer: ScheduledTimer) -> None:
        """Cancel a scheduled timer. Cancelling an unknown/expired timer is a no-op."""
        self._timers = [t for t in self._timers if t is not timer]

    def pending_timers(self) -> tuple[ScheduledTimer, ...]:
        """Return currently pending timers in absolute-time, insertion order."""
        return tuple(sorted(self._timers, key=lambda t: (t.fire_at, t.timer_id)))
