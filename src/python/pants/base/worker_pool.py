# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import multiprocessing
import threading
from multiprocessing.pool import ThreadPool


class SubprocPool:
    """Singleton for managing multiprocessing.Pool instances.

    Subprocesses (including multiprocessing.Pool workers) can inherit locks in poorly written
    libraries (eg zlib) if other threads in the parent process happen to be holding them at the
    moment the worker is fork()'ed. Thus it is important to create any subprocesses BEFORE
    starting any threads, or they may deadlock mysteriously when sent a particular piece of work.

    This is accomplished in pants by these initializing pools early, when creating the RunTracker.

    However, in tests, RunTrackers are created repeatedly, as part of creating Contexts that
    are used briefly and discarded. Creating a new subprocess pool every time is expensive, and will
    lead to os.fork failing once too many processes are spawned.

    To avoid this, the pools themselves are kept in this singleton and new RunTrackers re-use them.
    """

    _pool = None
    _lock = threading.Lock()
    _num_processes = multiprocessing.cpu_count()

    @classmethod
    def set_num_processes(cls, num_processes):
        cls._num_processes = num_processes

    @classmethod
    def foreground(cls):
        with cls._lock:
            if cls._pool is None:
                cls._pool = ThreadPool(processes=cls._num_processes)
            return cls._pool

    @classmethod
    def shutdown(cls, force):
        with cls._lock:
            old = cls._pool
            cls._pool = None

        if old:
            if force:
                old.terminate()
            else:
                old.close()
            old.join()
