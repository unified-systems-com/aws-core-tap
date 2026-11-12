"""Interim progress lines for a collection run, so an operator can see it is working.

The run log (``self.results``) is persisted once, when the run ends, so a long run is silent until then. These lines go
to the process log instead, where they can be followed as they happen. They hold counts, an entity type and seconds only:
never an account number, a resource id, a name or any response content.

``Progress.tick`` is called at the start of each manifest entry and writes a line at most once per ``interval`` seconds,
so a fast run adds a few lines and a slow one a steady heartbeat. It cannot speak during one long call: a heartbeat
that fires from a side thread would outlive an aborted run, and the next line after a slow entry names the entry that
was being read.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

#: Seconds between heartbeat lines.
DEFAULT_INTERVAL = 30.0


class Progress:
    def __init__(
        self,
        total_entries: int,
        *,
        interval: float = DEFAULT_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        emit: Callable[..., None] | None = None,
    ) -> None:
        self._total = total_entries
        self._interval = interval
        self._clock = clock
        self._emit = emit or logger.info
        self._started = clock()
        self._last = self._started

    def elapsed(self) -> float:
        return self._clock() - self._started

    def start(self, *, regions: int, partition: str, selected_run: bool) -> None:
        self._emit(
            "[7a1d] aws_core collection started: %d manifest entries across %d region(s) in partition %s%s",
            self._total,
            regions,
            partition,
            " (a selection is applied)" if selected_run else "",
        )

    def tick(self, done: int, entry: dict, *, nodes: int, edges: int) -> None:
        """Called before ``entry`` is read; ``done`` entries are finished. Writes a line if ``interval`` has passed."""
        now = self._clock()
        if now - self._last < self._interval:
            return
        self._last = now
        percent = 100 * done // self._total if self._total else 100
        self._emit(
            "[3e9b] aws_core collection: %d/%d entries (%d%%), now reading %s:%s, %d nodes and %d edges so far, %ds elapsed",
            done,
            self._total,
            percent,
            entry["service"],
            entry["entity_type"].removeprefix("aws_core__aws_"),
            nodes,
            edges,
            int(self.elapsed()),
        )

    def reads_finished(self, *, nodes: int, edges: int) -> None:
        self._emit(
            "[c52f] aws_core collection: reads finished after %ds; submitting %d nodes and %d edges",
            int(self.elapsed()),
            nodes,
            edges,
        )

    def finished(self, *, batches_imported: int) -> None:
        self._emit(
            "[94d6] aws_core collection finished after %ds: %d batch(es) imported", int(self.elapsed()), batches_imported
        )
