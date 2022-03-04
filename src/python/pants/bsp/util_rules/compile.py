# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
import time
import uuid
from dataclasses import dataclass

from pants.bsp.context import BSPContext
from pants.bsp.protocol import BSPHandlerMapping
from pants.bsp.spec.base import StatusCode, TaskId
from pants.bsp.spec.compile import CompileParams, CompileReport, CompileResult, CompileTask
from pants.bsp.spec.task import TaskFinishParams, TaskStartParams
from pants.build_graph.address import AddressInput
from pants.engine.fs import Workspace
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.rules import _uncacheable_rule, collect_rules
from pants.engine.target import FieldSet, WrappedTarget
from pants.engine.unions import UnionMembership, UnionRule, union

_logger = logging.getLogger(__name__)


@union
@dataclass(frozen=True)
class BSPCompileFieldSet(FieldSet):
    """FieldSet used to hook BSP compilation."""


@dataclass(frozen=True)
class BSPCompileResult:
    """Result of compilation of a target capable of target compilation."""

    status: StatusCode
    output_digest: Digest


class CompileRequestHandlerMapping(BSPHandlerMapping):
    method_name = "buildTarget/compile"
    request_type = CompileParams
    response_type = CompileResult


@_uncacheable_rule
async def bsp_compile_request(
    request: CompileParams,
    bsp_context: BSPContext,
    union_membership: UnionMembership,
    workspace: Workspace,
) -> CompileResult:
    compile_field_sets = union_membership.get(BSPCompileFieldSet)
    compile_results = []
    for bsp_target_id in request.targets:
        # TODO: MultiGet these all.

        wrapped_tgt = await Get(WrappedTarget, AddressInput, bsp_target_id.address_input)
        tgt = wrapped_tgt.target
        _logger.info(f"tgt = {tgt}")
        applicable_field_set_impls = []
        for impl in compile_field_sets:
            if impl.is_applicable(tgt):
                applicable_field_set_impls.append(impl)
        _logger.info(f"applicable_field_sets = {applicable_field_set_impls}")
        if len(applicable_field_set_impls) == 0:
            raise ValueError(f"no applicable field set for: {tgt.address}")
        elif len(applicable_field_set_impls) > 1:
            raise ValueError(f"ambiguous field set mapping, >1 for: {tgt.address}")

        field_set = applicable_field_set_impls[0].create(tgt)

        task_id = TaskId(id=request.origin_id or uuid.uuid4().hex)

        bsp_context.notify_client(
            TaskStartParams(
                task_id=task_id,
                event_time=int(time.time() * 1000),
                data=CompileTask(target=bsp_target_id),
            )
        )

        compile_result = await Get(BSPCompileResult, BSPCompileFieldSet, field_set)
        compile_results.append(compile_result)

        bsp_context.notify_client(
            TaskFinishParams(
                task_id=task_id,
                event_time=int(time.time() * 1000),
                status=compile_result.status,
                data=CompileReport(
                    target=bsp_target_id, origin_id=request.origin_id, errors=0, warnings=0
                ),
            )
        )

    output_digest = await Get(Digest, MergeDigests([r.output_digest for r in compile_results]))
    if output_digest != EMPTY_DIGEST:
        workspace.write_digest(output_digest, path_prefix=".pants.d/bsp")

    status_code = StatusCode.OK
    if any(r.status != StatusCode.OK for r in compile_results):
        status_code = StatusCode.ERROR

    return CompileResult(
        origin_id=request.origin_id,
        status_code=status_code.value,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(BSPHandlerMapping, CompileRequestHandlerMapping),
    )
