# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap
from dataclasses import dataclass
from typing import Iterable

from pants.backend.scala.lint.scala_lang_fmt import ScalaLangFmtRequest
from pants.backend.scala.lint.scalafmt.skip_field import SkipScalafmtField
from pants.backend.scala.lint.scalafmt.subsystem import ScalafmtSubsystem
from pants.backend.scala.target_types import ScalaSourceField
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import BashBinary, FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import JdkSetup
from pants.jvm.resolve.coursier_fetch import MaterializedClasspath, MaterializedClasspathRequest
from pants.jvm.resolve.jvm_tool import JvmToolLockfileRequest, JvmToolLockfileSentinel
from pants.testutil.rule_runner import logging
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class ScalafmtFieldSet(FieldSet):
    required_fields = (ScalaSourceField,)

    source: ScalaSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipScalafmtField).value


class ScalafmtRequest(ScalaLangFmtRequest, LintRequest):
    field_set_type = ScalafmtFieldSet


class ScalafmtToolLockfileSentinel(JvmToolLockfileSentinel):
    options_scope = ScalafmtSubsystem.options_scope


@dataclass(frozen=True)
class SetupRequest:
    request: ScalafmtRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process
    original_digest: Digest


@logging
@rule(level=LogLevel.DEBUG)
async def setup_google_java_format(
    setup_request: SetupRequest,
    tool: ScalafmtSubsystem,
    jdk_setup: JdkSetup,
    bash: BashBinary,
) -> Setup:
    source_files, tool_classpath, conf_digest = await MultiGet(
        Get(
            SourceFiles,
            SourceFilesRequest(field_set.source for field_set in setup_request.request.field_sets),
        ),
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                prefix="__toolcp",
                lockfiles=(tool.resolved_lockfile(),),
            ),
        ),
        # TODO: Figure out how to scan for the correct configuration file to use while also dealing with
        #  the seeming requirement that `version` must be set in the configuration file.
        Get(
            Digest,
            CreateDigest(
                [
                    FileContent(
                        path=".scalafmt.conf",
                        content=textwrap.dedent(
                            f"""\
                version = "{tool.version}"
                runner.dialect = scala213
                """
                        ).encode(),
                    )
                ]
            ),
        ),
    )

    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            [source_files_snapshot.digest, conf_digest, tool_classpath.digest, jdk_setup.digest]
        ),
    )

    def add_check_args() -> Iterable[str]:
        if setup_request.check_only:
            yield "--list"

    args = [
        *jdk_setup.args(bash, tool_classpath.classpath_entries()),
        "org.scalafmt.cli.Cli",
        "--config=.scalafmt.conf",
        "--non-interactive",
        *add_check_args(),
    ]
    args.extend(source_files.files)

    process = Process(
        argv=args,
        input_digest=input_digest,
        output_files=source_files_snapshot.files,
        append_only_caches=jdk_setup.append_only_caches,
        env=jdk_setup.env,
        description=f"Run `scalafmt` against {pluralize(len(setup_request.request.field_sets), 'file')}.",
        level=LogLevel.DEBUG,
    )

    return Setup(process, original_digest=source_files_snapshot.digest)


@rule(desc="Format with scalafmt", level=LogLevel.DEBUG)
async def scalafmt_fmt(field_sets: ScalafmtRequest, tool: ScalafmtSubsystem) -> FmtResult:
    if tool.skip:
        return FmtResult.skip(formatter_name="scalafmt")
    setup = await Get(Setup, SetupRequest(field_sets, check_only=False))
    result = await Get(ProcessResult, Process, setup.process)
    return FmtResult.from_process_result(
        result,
        original_digest=setup.original_digest,
        formatter_name="scalafmt",
        strip_chroot_path=True,
    )


@rule(desc="Lint with scalafmt", level=LogLevel.DEBUG)
async def scalafmt_lint(field_sets: ScalafmtRequest, tool: ScalafmtSubsystem) -> LintResults:
    if tool.skip:
        return LintResults([], linter_name="scalafmt")
    setup = await Get(Setup, SetupRequest(field_sets, check_only=True))
    result = await Get(FallibleProcessResult, Process, setup.process)
    lint_result = LintResult.from_fallible_process_result(result)
    return LintResults([lint_result], linter_name="scalafmt")


@rule
async def generate_scalafmt_lockfile_request(
    _: ScalafmtToolLockfileSentinel,
    tool: ScalafmtSubsystem,
) -> JvmToolLockfileRequest:
    return JvmToolLockfileRequest.from_tool(tool)


def rules():
    return [
        *collect_rules(),
        UnionRule(ScalaLangFmtRequest, ScalafmtRequest),
        UnionRule(JvmToolLockfileSentinel, ScalafmtToolLockfileSentinel),
    ]
