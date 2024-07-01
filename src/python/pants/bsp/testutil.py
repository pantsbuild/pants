# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
import os
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Thread
from typing import Any, BinaryIO, Dict, Iterable, Tuple

from pylsp_jsonrpc.endpoint import Endpoint  # type: ignore[import]
from pylsp_jsonrpc.streams import JsonRpcStreamReader, JsonRpcStreamWriter  # type: ignore[import]

from pants.bsp.context import BSPContext
from pants.bsp.protocol import BSPConnection
from pants.bsp.rules import rules as bsp_rules
from pants.engine.internals.native_engine import PyThreadLocals
from pants.testutil.rule_runner import RuleRunner


@dataclass(frozen=True)
class PipesForTest:
    server_reader: BinaryIO
    server_writer: BinaryIO
    client_writer: BinaryIO
    client_reader: BinaryIO


@contextmanager
def setup_pipes():
    server_reader_fd, client_writer_fd = os.pipe()
    server_reader = os.fdopen(server_reader_fd, "rb", buffering=0)
    client_writer = os.fdopen(client_writer_fd, "wb", buffering=0)

    client_reader_fd, server_writer_fd = os.pipe()
    client_reader = os.fdopen(client_reader_fd, "rb", buffering=0)
    server_writer = os.fdopen(server_writer_fd, "wb", buffering=0)

    wrapper = PipesForTest(
        server_reader=server_reader,
        server_writer=server_writer,
        client_writer=client_writer,
        client_reader=client_reader,
    )

    try:
        yield wrapper
    finally:
        server_reader.close()
        server_writer.close()
        client_writer.close()
        client_reader.close()


# A notification method name, and a subset of its fields.
NotificationSubset = Tuple[str, Dict[str, Any]]


@dataclass
class Notifications:
    _notifications: list[tuple[str, dict[str, Any]]]

    def _record(self, method_name: str, notification: dict[str, Any]) -> None:
        self._notifications.append((method_name, notification))

    def assert_received_unordered(self, expected: Iterable[NotificationSubset]) -> None:
        """Asserts that the buffer contains matching notifications, then clears the buffer."""
        expected = list(expected)
        for notification_method_name, notification in self._notifications:
            for i in range(len(expected)):
                candidate_method_name, candidate_subset = expected[i]
                if candidate_method_name != notification_method_name:
                    continue
                # If the candidate was a subset of the notification, then we've matched.
                if candidate_subset.items() <= notification.items():
                    expected.pop(i)
                    break
            else:
                raise AssertionError(
                    f"Received unexpected `{notification_method_name}` notification: {notification}"
                )

        if expected:
            raise AssertionError(f"Did not receive all expected notifications: {expected}")
        self._notifications.clear()


@contextmanager
def setup_bsp_server(
    rule_runner: RuleRunner | None = None, *, notification_names: set[str] | None = None
):
    rule_runner = rule_runner or RuleRunner(rules=bsp_rules())
    notification_names = notification_names or set()
    thread_locals = PyThreadLocals.get_for_current_thread()

    with setup_pipes() as pipes, rule_runner.pushd():
        context = BSPContext()
        rule_runner.set_session_values({BSPContext: context})
        conn = BSPConnection(
            rule_runner.scheduler,
            rule_runner.union_membership,
            context,
            pipes.server_reader,
            pipes.server_writer,
        )

        def run_bsp_server():
            thread_locals.set_for_current_thread()
            conn.run()

        bsp_thread = Thread(target=run_bsp_server)
        bsp_thread.daemon = True
        bsp_thread.start()

        client_reader = JsonRpcStreamReader(pipes.client_reader)
        client_writer = JsonRpcStreamWriter(pipes.client_writer)
        notifications = Notifications([])
        endpoint = Endpoint(
            {name: functools.partial(notifications._record, name) for name in notification_names},
            lambda msg: client_writer.write(msg),
        )

        def run_client():
            client_reader.listen(lambda msg: endpoint.consume(msg))

        client_thread = Thread(target=run_client)
        client_thread.daemon = True
        client_thread.start()

        try:
            yield endpoint, notifications
        finally:
            client_reader.close()
            client_writer.close()
