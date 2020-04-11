# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Set

import psutil


class ProcessStillRunning(AssertionError):
    """Raised when a process shouldn't be running but is."""


def _safe_iter_matching_processes(name: str) -> Iterator[psutil.Process]:
    for proc in psutil.process_iter():
        try:
            if name in "".join(proc.cmdline()):
                yield proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def _make_process_table(processes):
    line_tmpl = "{0:>7} {1:>7} {2}"
    proc_tuples = [(p.pid, p.ppid(), "".join(p.cmdline())) for p in processes]
    return "\n".join(
        [line_tmpl.format("PID", "PGID", "CMDLINE")]
        + [line_tmpl.format(*t) for t in sorted(proc_tuples)]
    )


@contextmanager
def no_lingering_process_by_command(name: str):
    """Asserts that no process exists for a given command with a helpful error, excluding existing
    processes outside of the scope of the contextmanager."""
    context = TrackedProcessesContext(name, set(_safe_iter_matching_processes(name)))
    yield context
    delta_processes = context.current_processes()
    if delta_processes:
        raise ProcessStillRunning(
            "{} {} processes lingered after tests:\n{}".format(
                len(delta_processes), name, _make_process_table(delta_processes)
            )
        )


@dataclass(frozen=True)
class TrackedProcessesContext:
    name: str
    before_processes: Set[psutil.Process]

    def current_processes(self) -> Set[psutil.Process]:
        """Returns the current set of matching processes created since the context was entered."""
        after_processes = set(_safe_iter_matching_processes(self.name))
        return after_processes.difference(self.before_processes)
