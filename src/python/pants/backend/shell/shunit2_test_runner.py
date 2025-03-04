# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
from dataclasses import dataclass
from typing import Any

from pants.backend.shell.subsystems.shell_setup import ShellSetup
from pants.backend.shell.subsystems.shunit2 import Shunit2
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
    RuntimePackageDependenciesField,
    TestDebugRequest,
    TestExtraEnv,
    TestFieldSet,
    TestRequest,
    TestResult,
    TestSubsystem,
    build_runtime_package_dependencies,
)
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules.external_tool import download_external_tool
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.core.util_rules.system_binaries import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    find_binary,
)
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, FileContent, MergeDigests
from pants.engine.internals.graph import transitive_targets as transitive_targets_get
from pants.engine.intrinsics import create_digest, get_digest_contents, merge_digests
from pants.engine.platform import Platform
from pants.engine.process import (
    InteractiveProcess,
    Process,
    ProcessCacheScope,
    ProcessWithRetries,
    execute_process_with_retry,
)
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import SourcesField, Target, TransitiveTargetsRequest
from pants.option.global_options import GlobalOptions
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel


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


class Shunit2TestRequest(TestRequest):
    tool_subsystem = Shunit2
    field_set_type = Shunit2FieldSet
    supports_debug = True


@dataclass(frozen=True)
class TestSetupRequest:
    field_set: Shunit2FieldSet


@dataclass(frozen=True)
class TestSetup:
    process: Process


class ShellNotConfigured(Exception):
    pass


SOURCE_SHUNIT2_REGEX = re.compile(rb"(?:source|\.)\s+[.${}/'\"\w]*shunit2\b['\"]?")


def add_source_shunit2(fc: FileContent, binary_name: str) -> FileContent:
    # NB: We always run tests from the build root, so we source `shunit2` relative to there.
    source_line = f"source ./{binary_name}".encode()

    lines: list[bytes] = []
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
    request: Shunit2RunnerRequest,
    shell_setup: ShellSetup.EnvironmentAware,
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
                f"(run `{bin_name()} help {Shunit2TestsGeneratorTarget.alias}` for valid shells)."
            )
        tgt_shell = parse_result

    path_request = BinaryPathRequest(
        binary_name=tgt_shell.name,
        search_path=shell_setup.executable_search_path,
        test=tgt_shell.binary_path_test,
    )
    paths = await find_binary(path_request, **implicitly())
    first_path = paths.first_path
    if not first_path:
        raise BinaryNotFoundError.from_request(
            path_request, rationale=f"run shunit2 on {request.address}"
        )
    return Shunit2Runner(tgt_shell, first_path)


@rule(desc="Setup shunit2", level=LogLevel.DEBUG)
async def setup_shunit2_for_target(
    request: TestSetupRequest,
    shell_setup: ShellSetup.EnvironmentAware,
    test_subsystem: TestSubsystem,
    test_extra_env: TestExtraEnv,
    shunit2: Shunit2,
    platform: Platform,
) -> TestSetup:
    shunit2_script, transitive_targets, built_package_dependencies = await concurrently(
        download_external_tool(shunit2.get_request(platform)),
        transitive_targets_get(
            TransitiveTargetsRequest([request.field_set.address]), **implicitly()
        ),
        build_runtime_package_dependencies(
            BuildPackageDependenciesRequest(request.field_set.runtime_package_dependencies)
        ),
    )

    dependencies_source_files_request = determine_source_files(
        SourceFilesRequest(
            (tgt.get(SourcesField) for tgt in transitive_targets.dependencies),
            for_sources_types=(ShellSourceField, FileSourceField, ResourceSourceField),
            enable_codegen=True,
        )
    )
    dependencies_source_files, field_set_sources = await concurrently(
        dependencies_source_files_request,
        determine_source_files(SourceFilesRequest([request.field_set.sources])),
    )

    field_set_digest_content = await get_digest_contents(field_set_sources.snapshot.digest)
    # `ShellTestSourceField` validates that there's exactly one file.
    test_file_content = field_set_digest_content[0]
    updated_test_file_content = add_source_shunit2(test_file_content, shunit2_script.exe)

    updated_test_digest, runner = await concurrently(
        create_digest(CreateDigest([updated_test_file_content])),
        determine_shunit2_shell(
            Shunit2RunnerRequest(
                request.field_set.address, test_file_content, request.field_set.shell
            ),
            **implicitly(),
        ),
    )

    input_digest = await merge_digests(
        MergeDigests(
            (
                shunit2_script.digest,
                updated_test_digest,
                dependencies_source_files.snapshot.digest,
                *(pkg.digest for pkg in built_package_dependencies),
            )
        )
    )

    env_dict = {
        "PATH": os.pathsep.join(shell_setup.executable_search_path),
        # Always include colors and strip them out for display below (if required), for better cache
        # hit rates
        "SHUNIT_COLOR": "always",
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
        timeout_seconds=request.field_set.timeout.calculate_from_global_options(test_subsystem),
        cache_scope=cache_scope,
    )
    return TestSetup(process)


@rule(desc="Run tests with Shunit2", level=LogLevel.DEBUG)
async def run_tests_with_shunit2(
    batch: Shunit2TestRequest.Batch[Shunit2FieldSet, Any],
    test_subsystem: TestSubsystem,
    global_options: GlobalOptions,
) -> TestResult:
    field_set = batch.single_element

    setup = await setup_shunit2_for_target(TestSetupRequest(field_set), **implicitly())
    results = await execute_process_with_retry(
        ProcessWithRetries(setup.process, test_subsystem.attempts_default)
    )
    return TestResult.from_fallible_process_result(
        process_results=results.results,
        address=field_set.address,
        output_setting=test_subsystem.output,
        output_simplifier=global_options.output_simplifier(),
    )


@rule(desc="Setup Shunit2 to run interactively", level=LogLevel.DEBUG)
async def setup_shunit2_debug_test(
    batch: Shunit2TestRequest.Batch[Shunit2FieldSet, Any],
) -> TestDebugRequest:
    setup = await setup_shunit2_for_target(TestSetupRequest(batch.single_element), **implicitly())
    return TestDebugRequest(
        InteractiveProcess.from_process(
            setup.process, forward_signals_to_process=False, restartable=True
        )
    )


def rules():
    return (
        *collect_rules(),
        *Shunit2TestRequest.rules(),
    )
