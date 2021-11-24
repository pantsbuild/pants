# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass

from pants.backend.shell.shell_setup import ShellSetup
from pants.backend.shell.target_types import (
    ShellSourceField,
    Shunit2Shell,
    Shunit2ShellField,
    Shunit2TestsGeneratorTarget,
    Shunit2TestSourceField,
    Shunit2TestTimeoutField,
    SkipShunit2TestsField,
)
from pants.core.goals.test import (
    BuildPackageDependenciesRequest,
    BuiltPackageDependencies,
    RuntimePackageDependenciesField,
    TestDebugRequest,
    TestExtraEnv,
    TestFieldSet,
    TestResult,
    TestSubsystem,
)
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    DownloadFile,
    FileContent,
    FileDigest,
    MergeDigests,
)
from pants.engine.process import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    FallibleProcessResult,
    InteractiveProcess,
    Process,
    ProcessCacheScope,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import SourcesField, Target, TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel
from pants.util.strutil import create_path_env_var


@dataclass(frozen=True)
class Shunit2FieldSet(TestFieldSet):
    required_fields = (Shunit2TestSourceField,)

    sources: Shunit2TestSourceField
    timeout: Shunit2TestTimeoutField
    shell: Shunit2ShellField
    runtime_package_dependencies: RuntimePackageDependenciesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipShunit2TestsField).value


@dataclass(frozen=True)
class TestSetupRequest:
    field_set: Shunit2FieldSet


@dataclass(frozen=True)
class TestSetup:
    process: Process


class ShellNotConfigured(Exception):
    pass


SOURCE_SHUNIT2_REGEX = re.compile(rb"(?:source|\.)\s+[.${}/'\"\w]*shunit2\b['\"]?")


def add_source_shunit2(fc: FileContent) -> FileContent:
    # NB: We always run tests from the build root, so we source `shunit2` relative to there.
    source_line = b"source ./shunit2"

    lines = []
    already_had_source = False
    for line in fc.content.splitlines():
        if SOURCE_SHUNIT2_REGEX.search(line):
            lines.append(SOURCE_SHUNIT2_REGEX.sub(source_line, line))
            already_had_source = True
        else:
            lines.append(line)

    if not already_had_source:
        lines.append(source_line)

    return FileContent(fc.path, b"\n".join(lines))


@dataclass(frozen=True)
class Shunit2RunnerRequest:
    address: Address
    test_file_content: FileContent
    shell_field: Shunit2ShellField


@dataclass(frozen=True)
class Shunit2Runner:
    shell: Shunit2Shell
    binary_path: BinaryPath


@rule(desc="Determine shunit2 shell")
async def determine_shunit2_shell(
    request: Shunit2RunnerRequest, shell_setup: ShellSetup
) -> Shunit2Runner:
    if request.shell_field.value is not None:
        tgt_shell = Shunit2Shell(request.shell_field.value)
    else:
        parse_result = Shunit2Shell.parse_shebang(request.test_file_content.content)
        if parse_result is None:
            raise ShellNotConfigured(
                f"Could not determine which shell to use to run shunit2 on {request.address}.\n\n"
                f"Please either specify the `{Shunit2ShellField.alias}` field or add a "
                f"shebang to {request.test_file_content.path} with one of the supported shells in "
                f"the format `!#/path/to/shell` or `!#/path/to/env shell`"
                f"(run `./pants help {Shunit2TestsGeneratorTarget.alias}` for valid shells)."
            )
        tgt_shell = parse_result

    env = await Get(Environment, EnvironmentRequest(["PATH"]))
    path_request = BinaryPathRequest(
        binary_name=tgt_shell.name,
        search_path=shell_setup.executable_search_path(env),
        test=tgt_shell.binary_path_test,
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, path_request)
    first_path = paths.first_path
    if not first_path:
        raise BinaryNotFoundError.from_request(
            path_request, rationale=f"run shunit2 on {request.address}"
        )
    return Shunit2Runner(tgt_shell, first_path)


@rule(desc="Setup shunit2", level=LogLevel.DEBUG)
async def setup_shunit2_for_target(
    request: TestSetupRequest,
    shell_setup: ShellSetup,
    test_subsystem: TestSubsystem,
    test_extra_env: TestExtraEnv,
    global_options: GlobalOptions,
) -> TestSetup:
    shunit2_download_file = DownloadFile(
        "https://raw.githubusercontent.com/kward/shunit2/b9102bb763cc603b3115ed30a5648bf950548097/shunit2",
        FileDigest("1f11477b7948150d1ca50cdd41d89be4ed2acd137e26d2e0fe23966d0e272cc5", 40987),
    )
    shunit2_script, transitive_targets, built_package_dependencies, env = await MultiGet(
        Get(Digest, DownloadFile, shunit2_download_file),
        Get(TransitiveTargets, TransitiveTargetsRequest([request.field_set.address])),
        Get(
            BuiltPackageDependencies,
            BuildPackageDependenciesRequest(request.field_set.runtime_package_dependencies),
        ),
        Get(Environment, EnvironmentRequest(["PATH"])),
    )

    dependencies_source_files_request = Get(
        SourceFiles,
        SourceFilesRequest(
            (tgt.get(SourcesField) for tgt in transitive_targets.dependencies),
            for_sources_types=(ShellSourceField, FileSourceField, ResourceSourceField),
            enable_codegen=True,
        ),
    )
    dependencies_source_files, field_set_sources = await MultiGet(
        dependencies_source_files_request,
        Get(SourceFiles, SourceFilesRequest([request.field_set.sources])),
    )

    field_set_digest_content = await Get(DigestContents, Digest, field_set_sources.snapshot.digest)
    # `ShellTestSourceField` validates that there's exactly one file.
    test_file_content = field_set_digest_content[0]
    updated_test_file_content = add_source_shunit2(test_file_content)

    updated_test_digest, runner = await MultiGet(
        Get(Digest, CreateDigest([updated_test_file_content])),
        Get(
            Shunit2Runner,
            Shunit2RunnerRequest(
                request.field_set.address, test_file_content, request.field_set.shell
            ),
        ),
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                shunit2_script,
                updated_test_digest,
                dependencies_source_files.snapshot.digest,
                *(pkg.digest for pkg in built_package_dependencies),
            )
        ),
    )

    env_dict = {
        "PATH": create_path_env_var(shell_setup.executable_search_path(env)),
        "SHUNIT_COLOR": "always" if global_options.options.colors else "none",
        **test_extra_env.env,
    }
    argv = (
        # Zsh requires extra args. See https://github.com/kward/shunit2/#-zsh.
        [runner.binary_path.path, "-o", "shwordsplit", "--", *field_set_sources.snapshot.files]
        if runner.shell == Shunit2Shell.zsh
        else [runner.binary_path.path, *field_set_sources.snapshot.files]
    )
    cache_scope = (
        ProcessCacheScope.PER_SESSION if test_subsystem.force else ProcessCacheScope.SUCCESSFUL
    )
    process = Process(
        argv=argv,
        input_digest=input_digest,
        description=f"Run shunit2 for {request.field_set.address}.",
        level=LogLevel.DEBUG,
        env=env_dict,
        timeout_seconds=request.field_set.timeout.value,
        cache_scope=cache_scope,
    )
    return TestSetup(process)


@rule(desc="Run tests with Shunit2", level=LogLevel.DEBUG)
async def run_tests_with_shunit2(
    field_set: Shunit2FieldSet, test_subsystem: TestSubsystem
) -> TestResult:
    setup = await Get(TestSetup, TestSetupRequest(field_set))
    result = await Get(FallibleProcessResult, Process, setup.process)
    return TestResult.from_fallible_process_result(
        result,
        address=field_set.address,
        output_setting=test_subsystem.output,
    )


@rule(desc="Setup Shunit2 to run interactively", level=LogLevel.DEBUG)
async def setup_shunit2_debug_test(field_set: Shunit2FieldSet) -> TestDebugRequest:
    setup = await Get(TestSetup, TestSetupRequest(field_set))
    return TestDebugRequest(
        InteractiveProcess.from_process(
            setup.process, forward_signals_to_process=False, restartable=True
        )
    )


def rules():
    return [*collect_rules(), UnionRule(TestFieldSet, Shunit2FieldSet)]
