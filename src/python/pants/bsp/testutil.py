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
    inbound_reader: BinaryIO
    inbound_writer: BinaryIO
    outbound_reader: BinaryIO
    outbound_writer: BinaryIO


@contextmanager
def setup_pipes():
    inbound_reader_fd, inbound_writer_fd = os.pipe()
    inbound_reader = os.fdopen(inbound_reader_fd, "rb", buffering=0)
    inbound_writer = os.fdopen(inbound_writer_fd, "wb", buffering=0)

    outbound_reader_fd, outbound_writer_fd = os.pipe()
    outbound_reader = os.fdopen(outbound_reader_fd, "rb", buffering=0)
    outbound_writer = os.fdopen(outbound_writer_fd, "wb", buffering=0)

    wrapper = PipesForTest(
        inbound_reader=inbound_reader,
        inbound_writer=inbound_writer,
        outbound_reader=outbound_reader,
        outbound_writer=outbound_writer,
    )

    try:
        yield wrapper
    finally:
        inbound_reader.close()
        inbound_writer.close()
        outbound_reader.close()
        outbound_writer.close()


@contextmanager
def setup_bsp_server():
    with setup_pipes() as pipes:
        context = BSPContext()
        rule_runner = RuleRunner(rules=bsp_rules(), extra_session_values={BSPContext: context})
        conn = BSPConnection(
            rule_runner.scheduler,
            rule_runner.union_membership,
            context,
            pipes.inbound_reader,
            pipes.outbound_writer,
        )

        def run_bsp_server():
            conn.run()

        bsp_thread = Thread(target=run_bsp_server)
        bsp_thread.daemon = True
        bsp_thread.start()

        client_reader = JsonRpcStreamReader(pipes.outbound_reader)
        client_writer = JsonRpcStreamWriter(pipes.inbound_writer)
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
