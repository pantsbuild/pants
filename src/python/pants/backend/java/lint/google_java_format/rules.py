# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from dataclasses import dataclass

from pants.backend.java.lint.google_java_format.skip_field import SkipGoogleJavaFormatField
from pants.backend.java.lint.google_java_format.subsystem import GoogleJavaFormatSubsystem
from pants.backend.java.target_types import JavaSourceField
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.process import execute_process_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.coursier_fetch import ToolClasspathRequest, materialize_classpath_for_tool
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoogleJavaFormatFieldSet(FieldSet):
    required_fields = (JavaSourceField,)

    source: JavaSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipGoogleJavaFormatField).value


class GoogleJavaFormatRequest(FmtTargetsRequest):
    field_set_type = GoogleJavaFormatFieldSet
    tool_subsystem = GoogleJavaFormatSubsystem
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Format with Google Java Format", level=LogLevel.DEBUG)
async def google_java_format_fmt(
    request: GoogleJavaFormatRequest.Batch,
    tool: GoogleJavaFormatSubsystem,
    jdk: InternalJdk,
) -> FmtResult:
    lockfile_request = GenerateJvmLockfileFromTool.create(tool)
    tool_classpath = await materialize_classpath_for_tool(
        ToolClasspathRequest(lockfile=lockfile_request)
    )

    toolcp_relpath = "__toolcp"
    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
    }

    maybe_java11_or_higher_options = []
    if jdk.jre_major_version >= 11:
        maybe_java11_or_higher_options = [
            "--add-exports=jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED",
            "--add-exports=jdk.compiler/com.sun.tools.javac.file=ALL-UNNAMED",
            "--add-exports=jdk.compiler/com.sun.tools.javac.parser=ALL-UNNAMED",
            "--add-exports=jdk.compiler/com.sun.tools.javac.tree=ALL-UNNAMED",
            "--add-exports=jdk.compiler/com.sun.tools.javac.util=ALL-UNNAMED",
        ]

    args = [
        *maybe_java11_or_higher_options,
        "com.google.googlejavaformat.java.Main",
        *(["--aosp"] if tool.aosp else []),
        "--replace",
        *request.files,
    ]

    result = await execute_process_or_raise(
        **implicitly(
            JvmProcess(
                jdk=jdk,
                argv=args,
                classpath_entries=tool_classpath.classpath_entries(toolcp_relpath),
                input_digest=request.snapshot.digest,
                extra_jvm_options=tool.jvm_options,
                extra_immutable_input_digests=extra_immutable_input_digests,
                extra_nailgun_keys=extra_immutable_input_digests,
                output_files=request.files,
                description=f"Run Google Java Format on {pluralize(len(request.files), 'file')}.",
                level=LogLevel.DEBUG,
            ),
        )
    )
    return await FmtResult.create(request, result)


def rules():
    return [
        *collect_rules(),
        *jvm_tool.rules(),
        *GoogleJavaFormatRequest.rules(),
        UnionRule(ExportableTool, GoogleJavaFormatSubsystem),
    ]
