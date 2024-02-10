# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, KeysView, Tuple

logger = logging.getLogger(__name__)


class PantsService(ABC):
    """Pants daemon service base class.

    The service lifecycle is made up of states described in the _ServiceState class, and controlled
    by a calling thread that is holding the Service `lifecycle_lock`. Under that lock, a caller
    can signal a service to "pause", "run", or "terminate" (see _ServiceState for more details).

    pantsd pauses all Services before forking a pantsd in order to ensure that no "relevant"
    locks are held (or awaited: see #6565) by threads that might not survive the fork. While paused,
    a Service must not have any threads running that might interact with any non-private locks.

    After forking, the pantsd (child) process should call `terminate()` to finish shutting down
    the service, and the parent process should call `resume()` to cause the service to resume running.
    """

    class ServiceError(Exception):
        pass

    def __init__(self):
        super().__init__()
        self.name = self.__class__.__name__
        self._state = _ServiceState()

    def setup(self, services: Tuple["PantsService", ...]):
        """Called before `run` to allow for service->service or other side-effecting setup."""
        self.services = services

    @abstractmethod
    def run(self):
        """The main entry-point for the service called by the service runner."""

    def mark_pausing(self):
        """Triggers pausing of the service, without waiting for it to have paused.

        See the class and _ServiceState pydocs.
        """
        self._state.mark_pausing()

    def await_paused(self):
        """Once a service has been marked pausing, waits for it to have paused.

        See the class and _ServiceState pydocs.
        """
        self._state.await_paused()

    def resume(self):
        """Triggers the service to resume running, without waiting.

        See the class and _ServiceState pydocs.
        """
        self._state.mark_running()

    def terminate(self):
        """Triggers termination of the service, without waiting.

        See the class and _ServiceState pydocs.
        """
        self._state.mark_terminating()


class _ServiceState:
    """A threadsafe state machine for controlling a service running in another thread.

    The state machine represents two stable states:
      Running
      Paused
    And two transitional states:
      Pausing
      Terminating

    The methods of this class allow a caller to ask the Service to transition states, and then wait
    for those transitions to occur.

    A simplifying assumption is that there is one service thread that interacts with the state, and
    only one controlling thread. In the case of `pantsd`, the "one calling thread" condition is
    protected by the service `lifecycle_lock`.

    A complicating assumption is that while a service thread is `Paused`, it must be in a position
    where it could safely disappear and never come back. This is accounted for by having the service
    thread wait on a Condition variable while Paused: testing indicates that for multiple Pythons
    on both OSX and Linux, this does not result in poisoning of the associated Lock.
    """

    _RUNNING = "Running"
    _PAUSED = "Paused"
    _PAUSING = "Pausing"
    _TERMINATING = "Terminating"

    def __init__(self):
        """Creates a ServiceState in the Running state."""
        self._state = self._RUNNING
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

    def _set_state(self, state, *valid_states):
        if valid_states and self._state not in valid_states:
            raise AssertionError(f"Cannot move {self} to `{state}` while it is `{self._state}`.")
        self._state = state
        self._condition.notify_all()

    def await_paused(self, timeout=None):
        """Blocks until the service is in the Paused state, then returns True.

        If a timeout is specified, the method may return False to indicate a timeout: with no
        timeout it will always (eventually) return True.

        Raises if the service is not currently in the Pausing state.
        """
        deadline = time.time() + timeout if timeout else None
        with self._lock:
            # Wait until the service transitions out of Pausing.
            while self._state != self._PAUSED:
                if self._state != self._PAUSING:
                    raise AssertionError(
                        "Cannot wait for {} to reach `{}` while it is in `{}`.".format(
                            self, self._PAUSED, self._state
                        )
                    )
                timeout = deadline - time.time() if deadline else None
                if timeout and timeout <= 0:
                    return False
                self._condition.wait(timeout=timeout)
            return True

    def maybe_pause(self, timeout=None):
        """Called by the service to indicate that it is pausable.

        If the service calls this method while the state is `Pausing`, the state will transition
        to `Paused`, and the service will block here until it is marked `Running` or `Terminating`.

        If the state is not currently `Pausing`, and a timeout is not passed, this method returns
        immediately. If a timeout is passed, this method blocks up to that number of seconds to wait
        to transition to `Pausing`.
        """
        deadline = time.time() + timeout if timeout else None
        with self._lock:
            while self._state != self._PAUSING:
                # If we've been terminated, or the deadline has passed, return.
                timeout = deadline - time.time() if deadline else None
                if self._state == self._TERMINATING or not timeout or timeout <= 0:
                    return
                # Otherwise, wait for the state to change.
                self._condition.wait(timeout=timeout)

            # Set Paused, and then wait until we are no longer Paused.
            self._set_state(self._PAUSED, self._PAUSING)
            while self._state == self._PAUSED:
                self._condition.wait()

    def mark_pausing(self):
        """Requests that the service move to the Paused state, without waiting for it to do so.

        Raises if the service is not currently in the Running state.
        """
        with self._lock:
            self._set_state(self._PAUSING, self._RUNNING)

    def mark_running(self):
        """Moves the service to the Running state.

        Raises if the service is not currently in the Paused state.
        """
        with self._lock:
            self._set_state(self._RUNNING, self._PAUSED)

    def mark_terminating(self):
        """Requests that the service move to the Terminating state, without waiting for it to do
        so."""
        with self._lock:
            self._set_state(self._TERMINATING)

    @property
    def is_terminating(self):
        """Returns True if the Service should currently be terminating.

        NB: `Terminating` does not have an associated "terminated" state, because the caller uses
        liveness of the service thread to determine when a service is terminated.
        """
        with self._lock:
            return self._state == self._TERMINATING


@dataclass(frozen=True)
class PantsServices:
    """A collection of running PantsServices threads."""

    JOIN_TIMEOUT_SECONDS = 1

    _service_threads: Dict[PantsService, threading.Thread]

    def __init__(self, services: Tuple[PantsService, ...] = ()) -> None:
        object.__setattr__(self, "_service_threads", self._start(services))

    @classmethod
    def _make_thread(cls, service):
        name = f"{service.__class__.__name__}Thread"
        t = threading.Thread(target=service.run, name=name)
        t.daemon = True
        return t

    @classmethod
    def _start(cls, services: Tuple[PantsService, ...]) -> Dict[PantsService, threading.Thread]:
        """Launch a thread per service."""

        for service in services:
            logger.debug(f"setting up service {service}")
            service.setup(services)

        service_thread_map = {service: cls._make_thread(service) for service in services}

        for service, service_thread in service_thread_map.items():
            logger.debug(f"starting service {service}")
            service_thread.start()

        return service_thread_map

    @property
    def services(self) -> KeysView[PantsService]:
        return self._service_threads.keys()

    def are_all_alive(self) -> bool:
        """Return true if all services threads are still alive, and false if any have died.

        This method does not have sideeffects: if one service thread has died, the rest should be
        killed and joined via `self.shutdown()`.
        """
        for service, service_thread in self._service_threads.items():
            if not service_thread.is_alive():
                logger.error(f"service failure for {service}.")
                return False
        return True

    def shutdown(self) -> None:
        """Shut down and join all service threads."""
        for service, service_thread in self._service_threads.items():
            service.terminate()
        for service, service_thread in self._service_threads.items():
            logger.debug(f"terminating pantsd service: {service}")
            service_thread.join(self.JOIN_TIMEOUT_SECONDS)
