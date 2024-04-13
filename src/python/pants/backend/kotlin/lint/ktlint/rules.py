# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from dataclasses import dataclass

from pants.backend.kotlin.lint.ktlint.skip_field import SkipKtlintField
from pants.backend.kotlin.lint.ktlint.subsystem import KtlintSubsystem
from pants.backend.kotlin.target_types import KotlinSourceField
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, GenerateJvmToolLockfileSentinel
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KtlintFieldSet(FieldSet):
    required_fields = (KotlinSourceField,)

    source: KotlinSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipKtlintField).value


class KtlintRequest(FmtTargetsRequest):
    field_set_type = KtlintFieldSet
    tool_subsystem = KtlintSubsystem
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


class KtlintToolLockfileSentinel(GenerateJvmToolLockfileSentinel):
    resolve_name = KtlintSubsystem.options_scope


@rule(desc="Format with Ktlint", level=LogLevel.DEBUG)
async def ktlint_fmt(
    request: KtlintRequest.Batch, tool: KtlintSubsystem, jdk: InternalJdk
) -> FmtResult:
    lockfile_request = await Get(GenerateJvmLockfileFromTool, KtlintToolLockfileSentinel())
    tool_classpath = await Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request))

    toolcp_relpath = "__toolcp"
    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
    }

    args = [
        "com.pinterest.ktlint.Main",
        "-F",
        *request.files,
    ]

    result = await Get(
        ProcessResult,
        JvmProcess(
            jdk=jdk,
            argv=args,
            classpath_entries=tool_classpath.classpath_entries(toolcp_relpath),
            input_digest=request.snapshot.digest,
            extra_jvm_options=tool.jvm_options,
            extra_immutable_input_digests=extra_immutable_input_digests,
            extra_nailgun_keys=extra_immutable_input_digests,
            output_files=request.files,
            description=f"Run Ktlint on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )

    return await FmtResult.create(request, result)


@rule
def generate_ktlint_lockfile_request(
    _: KtlintToolLockfileSentinel, tool: KtlintSubsystem
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(tool)


def rules():
    return [
        *collect_rules(),
        *jvm_tool.rules(),
        *KtlintRequest.rules(),
        UnionRule(GenerateToolLockfileSentinel, KtlintToolLockfileSentinel),
    ]
