# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Thread
from typing import BinaryIO

from pylsp_jsonrpc.endpoint import Endpoint  # type: ignore[import]
from pylsp_jsonrpc.streams import JsonRpcStreamReader, JsonRpcStreamWriter  # type: ignore[import]

from pants.bsp.context import BSPContext
from pants.bsp.protocol import BSPConnection
from pants.bsp.rules import rules as bsp_rules
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


@contextmanager
def setup_bsp_server():
    with setup_pipes() as pipes:
        context = BSPContext()
        rule_runner = RuleRunner(rules=bsp_rules(), extra_session_values={BSPContext: context})
        conn = BSPConnection(
            rule_runner.scheduler,
            rule_runner.union_membership,
            context,
            pipes.server_reader,
            pipes.server_writer,
        )

        def run_bsp_server():
            conn.run()

        bsp_thread = Thread(target=run_bsp_server)
        bsp_thread.daemon = True
        bsp_thread.start()

        client_reader = JsonRpcStreamReader(pipes.client_reader)
        client_writer = JsonRpcStreamWriter(pipes.client_writer)
        endpoint = Endpoint({}, lambda msg: client_writer.write(msg))

        def run_client():
            client_reader.listen(lambda msg: endpoint.consume(msg))

        client_thread = Thread(target=run_client)
        client_thread.daemon = True
        client_thread.start()

        try:
            yield endpoint
        finally:
            client_reader.close()
            client_writer.close()
