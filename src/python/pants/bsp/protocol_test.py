# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import BinaryIO

import pytest
from pylsp_jsonrpc.endpoint import Endpoint  # type: ignore[import]
from pylsp_jsonrpc.exceptions import JsonRpcException, JsonRpcMethodNotFound  # type: ignore[import]
from pylsp_jsonrpc.streams import JsonRpcStreamReader, JsonRpcStreamWriter  # type: ignore[import]

from pants.bsp.protocol import BSPConnection
from pants.bsp.rules import rules as bsp_rules
from pants.engine.internals.scheduler_test_base import SchedulerTestBase


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


class TestBSPConnection(SchedulerTestBase):
    def test_errors_for_uninitialized_connection(self, tmp_path: Path) -> None:
        with setup_pipes() as pipes:
            # TODO: This code should be moved to a context manager. For now, only the pipes are managed
            # with a context manager.
            scheduler = self.mk_scheduler(tmp_path, [*bsp_rules()])
            conn = BSPConnection(scheduler, pipes.inbound_reader, pipes.outbound_writer)

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

            response_fut = endpoint.request("foo")
            with pytest.raises(JsonRpcException) as exc_info:
                response_fut.result(timeout=15)
            assert exc_info.value.code == -32002
            assert exc_info.value.message == "Client must first call `build/initialize`."

            response_fut = endpoint.request("build/initialize")
            with pytest.raises(JsonRpcMethodNotFound) as exc_info:
                response_fut.result(timeout=15)
            assert exc_info.value.code == -32601
            assert exc_info.value.message == "Method Not Found: build/initialize"
