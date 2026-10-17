"""
Level 1 — Event journal.

An append-only, in-memory event store that supports:
  - Sequential append with a monotonic sequence number.
  - Cursor-based replay (read from position N onward).
  - Simple duplicate deduplication by observation_id.
  - Pluggable persistence: swap ``InMemoryJournal`` for a JetStream-backed
    implementation without changing the consumer API.

Event record fields follow structure.md / inference.md:

    event_id · source_id + source_sequence + source_boot_id
    observed_at + received_at · coordinate_frame + units
    measurement + uncertainty · schema_version
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator, List, Optional

from simulator.data_models.observation import Observation


# ---------------------------------------------------------------------------
# Journal entry
# ---------------------------------------------------------------------------

@dataclass
class JournalEntry:
    """One committed event in the journal."""
    sequence:    int            # monotonically increasing, 1-based
    event_id:    str = field(default_factory=lambda: str(uuid.uuid4()))
    observation: Optional[Observation] = None
    committed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_replay:   bool = False   # True when re-ingested from a historical dump


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseJournal:
    """
    Minimal interface every journal implementation must satisfy.

    ``append``  — commit a new entry; raises DuplicateEventError on re-submission.
    ``read``    — iterator from a given sequence position (inclusive).
    ``latest``  — current head sequence number (0 when empty).
    """

    class DuplicateEventError(Exception):
        pass

    def append(self, obs: Observation) -> JournalEntry:
        raise NotImplementedError

    def read(self, from_sequence: int = 1) -> Iterator[JournalEntry]:
        raise NotImplementedError

    def latest(self) -> int:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------

class InMemoryJournal(BaseJournal):
    """
    Thread-safe in-memory journal suitable for the simulator prototype.

    Replace with a durable JetStream consumer for production use.
    Deduplication is by ``observation_id``; late / replayed data is
    accepted and flagged with ``is_replay=True`` if its ``observed_at``
    pre-dates the journal's start time.
    """

    def __init__(self) -> None:
        self._entries:    List[JournalEntry] = []
        self._seen_ids:   set[str]           = set()
        self._lock:       threading.Lock     = threading.Lock()
        self._start_time: Optional[datetime] = None

    # ------------------------------------------------------------------
    def append(self, obs: Observation) -> JournalEntry:
        with self._lock:
            if obs.observation_id in self._seen_ids:
                raise BaseJournal.DuplicateEventError(
                    f"event {obs.observation_id} already in journal"
                )

            now = datetime.now(timezone.utc)
            if self._start_time is None:
                self._start_time = now

            is_replay = False
            if obs.observed_at is not None:
                ot = obs.observed_at if obs.observed_at.tzinfo else obs.observed_at.replace(tzinfo=timezone.utc)
                if ot < self._start_time:
                    is_replay = True

            seq = len(self._entries) + 1
            entry = JournalEntry(
                sequence=seq,
                observation=obs,
                committed_at=now,
                is_replay=is_replay,
            )
            self._entries.append(entry)
            self._seen_ids.add(obs.observation_id)
            return entry

    # ------------------------------------------------------------------
    def read(self, from_sequence: int = 1) -> Iterator[JournalEntry]:
        """
        Yield entries from ``from_sequence`` onward.

        Safe to call concurrently; takes a snapshot of the current length to
        avoid indefinite iteration if the journal is still being appended to.
        """
        with self._lock:
            snapshot = list(self._entries)
        for entry in snapshot:
            if entry.sequence >= from_sequence:
                yield entry

    # ------------------------------------------------------------------
    def latest(self) -> int:
        with self._lock:
            return self._entries[-1].sequence if self._entries else 0

    # ------------------------------------------------------------------
    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    # ------------------------------------------------------------------
    def replay_all(self) -> Iterator[JournalEntry]:
        """
        Re-emit every entry in order, marked ``is_replay=True``.

        Used for recovery: the decision engine re-processes history to rebuild
        track and incident state without producing duplicate handoffs.
        """
        for entry in self.read(from_sequence=1):
            replayed = JournalEntry(
                sequence=entry.sequence,
                event_id=entry.event_id,
                observation=entry.observation,
                committed_at=entry.committed_at,
                is_replay=True,
            )
            yield replayed
