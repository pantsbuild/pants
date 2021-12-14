# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
from dataclasses import dataclass

from pants.backend.java.lint.google_java_format.skip_field import SkipGoogleJavaFormatField
from pants.backend.java.lint.google_java_format.subsystem import GoogleJavaFormatSubsystem
from pants.backend.java.lint.java_fmt import JavaFmtRequest
from pants.backend.java.target_types import JavaSourceField
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import BashBinary, FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import JdkSetup
from pants.jvm.resolve.coursier_fetch import MaterializedClasspath, MaterializedClasspathRequest
from pants.jvm.resolve.jvm_tool import JvmToolLockfileRequest, JvmToolLockfileSentinel
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class GoogleJavaFormatFieldSet(FieldSet):
    required_fields = (JavaSourceField,)

    source: JavaSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipGoogleJavaFormatField).value


class GoogleJavaFormatRequest(JavaFmtRequest, LintRequest):
    field_set_type = GoogleJavaFormatFieldSet


class GoogleJavaFormatToolLockfileSentinel(JvmToolLockfileSentinel):
    options_scope = GoogleJavaFormatSubsystem.options_scope


@dataclass(frozen=True)
class SetupRequest:
    request: GoogleJavaFormatRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process
    original_digest: Digest


@rule(level=LogLevel.DEBUG)
async def setup_google_java_format(
    setup_request: SetupRequest,
    tool: GoogleJavaFormatSubsystem,
    jdk_setup: JdkSetup,
    bash: BashBinary,
) -> Setup:
    source_files, tool_classpath = await MultiGet(
        Get(
            SourceFiles,
            SourceFilesRequest(field_set.source for field_set in setup_request.request.field_sets),
        ),
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                lockfiles=(tool.resolved_lockfile(),),
            ),
        ),
    )

    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    toolcp_relpath = "__toolcp"
    immutable_input_digests = {
        **jdk_setup.immutable_input_digests,
        toolcp_relpath: tool_classpath.digest,
    }

    maybe_java16_or_higher_options = []
    if jdk_setup.jre_major_version >= 16:
        maybe_java16_or_higher_options = [
            "--add-exports=jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED",
            "--add-exports=jdk.compiler/com.sun.tools.javac.file=ALL-UNNAMED",
            "--add-exports=jdk.compiler/com.sun.tools.javac.parser=ALL-UNNAMED",
            "--add-exports=jdk.compiler/com.sun.tools.javac.tree=ALL-UNNAMED",
            "--add-exports=jdk.compiler/com.sun.tools.javac.util=ALL-UNNAMED",
        ]

    args = [
        *jdk_setup.args(bash, tool_classpath.classpath_entries(toolcp_relpath)),
        *maybe_java16_or_higher_options,
        "com.google.googlejavaformat.java.Main",
        *(["--aosp"] if tool.aosp else []),
        "--dry-run" if setup_request.check_only else "--replace",
        *source_files.files,
    ]

    process = Process(
        argv=args,
        input_digest=source_files_snapshot.digest,
        immutable_input_digests=immutable_input_digests,
        output_files=source_files_snapshot.files,
        append_only_caches=jdk_setup.append_only_caches,
        env=jdk_setup.env,
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
    result = await Get(ProcessResult, Process, setup.process)
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
    result = await Get(FallibleProcessResult, Process, setup.process)
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
async def generate_google_java_format_lockfile_request(
    _: GoogleJavaFormatToolLockfileSentinel,
    tool: GoogleJavaFormatSubsystem,
) -> JvmToolLockfileRequest:
    return JvmToolLockfileRequest.from_tool(tool)


def rules():
    return [
        *collect_rules(),
        UnionRule(JvmToolLockfileSentinel, GoogleJavaFormatToolLockfileSentinel),
    ]
