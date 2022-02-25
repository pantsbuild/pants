# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import time

from pants.bsp.context import BSPContext
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import StatusCode, TaskId
from pants.bsp.spec.compile import CompileParams, CompileReport, CompileResult, CompileTask

# -----------------------------------------------------------------------------------------------
# Compile Request
# See https://build-server-protocol.github.io/docs/specification.html#compile-request
# -----------------------------------------------------------------------------------------------
from pants.bsp.spec.task import TaskFinishParams, TaskStartParams
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule


class CompileRequestHandlerMapping(BSPHandlerMapping):
    method_name = "buildTarget/compile"
    request_type = CompileParams
    response_type = CompileResult


@rule
async def bsp_compile_request(request: CompileParams, bsp_context: BSPContext) -> CompileResult:
    origin_id = request.origin_id or "compile-task"
    for i, target in enumerate(request.targets):
        task_id = TaskId(id=f"{origin_id}-{i}")
        bsp_context.notify_client(
            TaskStartParams(
                task_id=task_id,
                event_time=int(time.time() * 1000),
                data=CompileTask(target=target),
            )
        )

    for i, target in enumerate(request.targets):
        task_id = TaskId(id=f"{origin_id}-{i}")
        bsp_context.notify_client(
            TaskFinishParams(
                task_id=task_id,
                status=StatusCode.ERROR,
                data=CompileReport(target=target, origin_id=origin_id),
            )
        )

    return CompileResult(
        origin_id=request.origin_id,
        status_code=1,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(BSPHandlerMapping, CompileRequestHandlerMapping),
    )
