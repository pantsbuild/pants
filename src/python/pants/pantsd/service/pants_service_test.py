# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import threading

import pytest

from pants.pantsd.service.pants_service import PantsService


class RunnableTestService(PantsService):
    def run(self):
        pass


@pytest.fixture
def service() -> RunnableTestService:
    return RunnableTestService()


def test_init(service: RunnableTestService) -> None:
    assert bool(service.name) is True


def test_run_abstract() -> None:
    with pytest.raises(TypeError):
        PantsService()  # type: ignore[abstract]


def test_terminate(service: RunnableTestService) -> None:
    service.terminate()
    assert service._state.is_terminating


def test_maybe_pause(service: RunnableTestService) -> None:
    # Confirm that maybe_pause with/without a timeout does not deadlock when we are not
    # marked Pausing/Paused.
    service._state.maybe_pause(timeout=None)
    service._state.maybe_pause(timeout=0.5)


def test_pause_and_resume(service: RunnableTestService) -> None:
    service.mark_pausing()
    # Confirm that we don't transition to Paused without a service thread to maybe_pause.
    assert service._state.await_paused(timeout=0.5) is False
    # Spawn a thread to call maybe_pause.
    t = threading.Thread(target=service._state.maybe_pause)
    t.daemon = True
    t.start()
    # Confirm that we observe the pause from the main thread, and that the child thread pauses
    # there without exiting.
    assert service._state.await_paused(timeout=5) is True
    t.join(timeout=0.5)
    assert t.is_alive() is True
    # Resume the service, and confirm that the child thread exits.
    service.resume()
    t.join(timeout=5)
    assert t.is_alive() is False
