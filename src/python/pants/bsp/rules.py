# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pylsp_jsonrpc.exceptions import JsonRpcMethodNotFound  # type: ignore[import]

from pants.bsp.protocol import BSPRequest, BSPResponse
from pants.engine.rules import QueryRule, collect_rules, rule


@rule
async def dispatch_bsp_request(request: BSPRequest) -> BSPResponse:
    raise JsonRpcMethodNotFound.of(request.method_name)


def rules():
    return (
        *collect_rules(),
        QueryRule(BSPResponse, (BSPRequest,)),
    )
