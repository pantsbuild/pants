# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Thread
from typing import BinaryIO

import pytest
from pylsp_jsonrpc.endpoint import Endpoint  # type: ignore[import]
from pylsp_jsonrpc.exceptions import JsonRpcException  # type: ignore[import]
from pylsp_jsonrpc.streams import JsonRpcStreamReader, JsonRpcStreamWriter  # type: ignore[import]

from pants.bsp.protocol import BSPConnection
from pants.bsp.rules import rules as bsp_rules
from pants.bsp.spec import (
    BuildClientCapabilities,
    InitializeBuildParams,
    InitializeBuildResult,
    WorkspaceBuildTargetsParams,
    WorkspaceBuildTargetsResult,
)
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


def test_basic_bsp_protocol() -> None:
    with setup_pipes() as pipes:
        # TODO: This code should be moved to a context manager. For now, only the pipes are managed
        # with a context manager.
        rule_runner = RuleRunner(rules=bsp_rules())
        conn = BSPConnection(rule_runner.scheduler, pipes.inbound_reader, pipes.outbound_writer)

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

        init_request = InitializeBuildParams(
            display_name="test",
            version="0.0.0",
            bsp_version="0.0.0",
            root_uri="https://example.com",
            capabilities=BuildClientCapabilities(language_ids=()),
            data={"test": "foo"},
        )
        response_fut = endpoint.request("build/initialize", init_request.to_json_dict())
        raw_response = response_fut.result(timeout=15)
        response = InitializeBuildResult.from_json_dict(raw_response)
        assert response.display_name == "Pants"
        assert response.bsp_version == "2.0.0"

        build_targets_request = WorkspaceBuildTargetsParams()
        response_fut = endpoint.request(
            "workspace/buildTargets", build_targets_request.to_json_dict()
        )
        raw_response = response_fut.result(timeout=15)
        response = WorkspaceBuildTargetsResult.from_json_dict(raw_response)
        assert response.targets == ()
