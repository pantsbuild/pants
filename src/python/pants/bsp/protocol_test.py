# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest
from pylsp_jsonrpc.exceptions import JsonRpcException  # type: ignore[import]

from pants.bsp.spec.lifecycle import (
    BuildClientCapabilities,
    InitializeBuildParams,
    InitializeBuildResult,
)
from pants.bsp.spec.targets import WorkspaceBuildTargetsParams, WorkspaceBuildTargetsResult
from pants.bsp.testutil import setup_bsp_server


def test_basic_bsp_protocol() -> None:
    with setup_bsp_server() as (endpoint, _):
        with pytest.raises(JsonRpcException) as exc_info:
            response_fut = endpoint.request("foo")
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
