# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
import logging
from dataclasses import dataclass

from pants.backend.java.lint.google_java_format.skip_field import SkipGoogleJavaFormatField
from pants.backend.java.lint.google_java_format.subsystem import GoogleJavaFormatSubsystem
from pants.backend.java.target_types import JavaSourceField
from pants.core.goals.fmt import FmtRequest, FmtResult
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import JdkSetup, JvmProcess
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
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


class GoogleJavaFormatRequest(FmtRequest, LintRequest):
    field_set_type = GoogleJavaFormatFieldSet


class GoogleJavaFormatToolLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = GoogleJavaFormatSubsystem.options_scope


@dataclass(frozen=True)
class SetupRequest:
    request: GoogleJavaFormatRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: JvmProcess
    original_digest: Digest


@rule(level=LogLevel.DEBUG)
async def setup_google_java_format(
    setup_request: SetupRequest,
    tool: GoogleJavaFormatSubsystem,
    jdk_setup: JdkSetup,
) -> Setup:

    lockfile_request = await Get(
        GenerateJvmLockfileFromTool, GoogleJavaFormatToolLockfileSentinel()
    )
    source_files, tool_classpath = await MultiGet(
        Get(
            SourceFiles,
            SourceFilesRequest(field_set.source for field_set in setup_request.request.field_sets),
        ),
        Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request)),
    )

    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    toolcp_relpath = "__toolcp"
    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
    }

    maybe_java11_or_higher_options = []
    if jdk_setup.jre_major_version >= 11:
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
        "--dry-run" if setup_request.check_only else "--replace",
        *source_files.files,
    ]

    process = JvmProcess(
        argv=args,
        classpath_entries=tool_classpath.classpath_entries(toolcp_relpath),
        input_digest=source_files_snapshot.digest,
        extra_immutable_input_digests=extra_immutable_input_digests,
        extra_nailgun_keys=extra_immutable_input_digests,
        output_files=source_files_snapshot.files,
        description=f"Run Google Java Format on {pluralize(len(setup_request.request.field_sets), 'file')}.",
        level=LogLevel.DEBUG,
    )

    return Setup(process, original_digest=source_files_snapshot.digest)


@rule(desc="Format with Google Java Format", level=LogLevel.DEBUG)
async def google_java_format_fmt(
    field_sets: GoogleJavaFormatRequest, tool: GoogleJavaFormatSubsystem
) -> FmtResult:
    if tool.skip:
        return FmtResult.skip(formatter_name="Google Java Format")
    setup = await Get(Setup, SetupRequest(field_sets, check_only=False))
    result = await Get(ProcessResult, JvmProcess, setup.process)
    return FmtResult.from_process_result(
        result,
        original_digest=setup.original_digest,
        formatter_name="Google Java Format",
        strip_chroot_path=True,
    )


@rule(desc="Lint with Google Java Format", level=LogLevel.DEBUG)
async def google_java_format_lint(
    field_sets: GoogleJavaFormatRequest, tool: GoogleJavaFormatSubsystem
) -> LintResults:
    if tool.skip:
        return LintResults([], linter_name="Google Java Format")
    setup = await Get(Setup, SetupRequest(field_sets, check_only=True))
    result = await Get(FallibleProcessResult, JvmProcess, setup.process)
    lint_result = LintResult.from_fallible_process_result(result)
    if lint_result.exit_code == 0 and lint_result.stdout.strip() != "":
        # Note: The formetter returns success even if it would have reformatted the files.
        # When this occurs, convert the LintResult into a failure.
        lint_result = dataclasses.replace(
            lint_result,
            exit_code=1,
            stdout=f"The following Java files require formatting:\n{lint_result.stdout}\n",
        )
    return LintResults([lint_result], linter_name="Google Java Format")


@rule
def generate_google_java_format_lockfile_request(
    _: GoogleJavaFormatToolLockfileSentinel, tool: GoogleJavaFormatSubsystem
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(tool)


def rules():
    return [
        *collect_rules(),
        *jvm_tool.rules(),
        UnionRule(FmtRequest, GoogleJavaFormatRequest),
        UnionRule(LintRequest, GoogleJavaFormatRequest),
        UnionRule(GenerateToolLockfileSentinel, GoogleJavaFormatToolLockfileSentinel),
    ]
