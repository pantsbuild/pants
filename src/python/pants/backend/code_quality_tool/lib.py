# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import ClassVar, Type

from pants.backend.adhoc.target_types import (
    AdhocToolArgumentsField,
    AdhocToolExecutionDependenciesField,
    AdhocToolRunnableDependenciesField,
    AdhocToolRunnableField,
)
from pants.core.goals.fix import FixResult
from pants.core.goals.fmt import FmtFilesRequest
from pants.core.goals.lint import LintFilesRequest, LintResult
from pants.core.goals.run import RunFieldSet, RunInSandboxRequest
from pants.core.util_rules.adhoc_process_support import (
    ExtraSandboxContents,
    MergeExtraSandboxContents,
    ResolvedExecutionDependencies,
    ResolveExecutionDependenciesRequest,
)
from pants.core.util_rules.environments import EnvironmentNameRequest
from pants.core.util_rules.partitions import PartitionMetadata, Partitions
from pants.engine.addresses import Addresses
from pants.engine.environment import EnvironmentName
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import (
    EMPTY_DIGEST,
    Address,
    AddressInput,
    Digest,
    FilespecMatcher,
    MergeDigests,
    Snapshot,
)
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    StringSequenceField,
    Target,
    Targets,
)
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.strutil import Simplifier


class ByoFileGlobIncludeField(StringSequenceField):
    alias: ClassVar[str] = "file_glob_include"
    required = True


class ByoFileGlobExcludeField(StringSequenceField):
    alias: ClassVar[str] = "file_glob_exclude"
    required = False
    default = ()


class CodeQualityToolTarget(Target):
    alias: ClassVar[str] = "code_quality_tool"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        AdhocToolRunnableField,
        AdhocToolArgumentsField,
        AdhocToolExecutionDependenciesField,
        AdhocToolRunnableDependenciesField,
        ByoFileGlobIncludeField,
        ByoFileGlobExcludeField,
    )


class ByoGoal:
    goal: str
    request_superclass: Type[LintFilesRequest]
    skippable: list[str]
    result_class: type

    @classmethod
    def create_result(cls, request, process_result, output):
        raise NotImplementedError

    @classmethod
    def output_files_to_read(cls, request: LintFilesRequest.Batch):
        raise NotImplementedError


class ByoLintGoal(ByoGoal):
    goal = "lint"
    request_superclass = LintFilesRequest
    skippable = ["lint"]
    result_class = LintResult

    @classmethod
    def create_result(cls, request, process_result, output):
        return LintResult.create(request, process_result)

    @classmethod
    def output_files_to_read(cls, request: LintFilesRequest.Batch):
        return None


class ByoFmtGoal(ByoGoal):
    goal = "fmt"
    request_superclass = FmtFilesRequest
    skippable = ["lint", "fmt"]
    result_class = FixResult

    @classmethod
    def create_result(cls, request, process_result, output):
        return FixResult(
            input=request.snapshot,
            output=output,
            stdout=Simplifier().simplify(process_result.stdout),
            stderr=Simplifier().simplify(process_result.stderr),
            tool_name=request.tool_name,
        )

    @classmethod
    def output_files_to_read(cls, request: FmtFilesRequest.Batch):
        return request.files


@dataclass
class CodeQualityToolConfig:
    goal: str
    target: str
    name: str
    scope: str

    @property
    def _goal(self) -> ByoGoal:
        if self.goal == "fmt":
            return ByoFmtGoal
        elif self.goal == "lint":
            return ByoLintGoal
        else:
            raise ValueError(f"Unknown goal {self.goal}")


def build_rules(cfg: CodeQualityToolConfig):
    goal = cfg._goal

    class ByoTool(Subsystem):
        options_scope = cfg.scope
        name = cfg.name
        help = f"{cfg.goal.capitalize()} with {cfg.name}. Tool defined in {cfg.target}"

        skip = SkipOption(*goal.skippable)
        linter = cfg.target

    request_superclass = goal.request_superclass

    class ByoToolRequest(request_superclass):
        tool_subsystem = ByoTool

    @rule(canonical_name_suffix=cfg.scope)
    async def partition_inputs(
        request: ByoToolRequest.PartitionRequest, subsystem: ByoTool
    ) -> Partitions[str, PartitionMetadata]:
        if subsystem.skip:
            return Partitions()

        linter_address_str = subsystem.linter
        linter_address = await Get(
            Address,
            AddressInput,
            AddressInput.parse(linter_address_str, description_of_origin=f"ByoTool linter target"),
        )

        addresses = Addresses((linter_address,))
        addresses.expect_single()

        linter_targets = await Get(Targets, Addresses, addresses)
        linter = linter_targets[0]

        matching_filepaths = FilespecMatcher(
            includes=linter[ByoFileGlobIncludeField].value,
            excludes=linter[ByoFileGlobExcludeField].value,
        ).matches(request.files)

        return Partitions.single_partition(sorted(matching_filepaths))

    result_class = goal.result_class

    @rule(canonical_name_suffix=cfg.scope)
    async def run_byotool(request: ByoToolRequest.Batch, subsystem: ByoTool) -> result_class:

        if goal is ByoLintGoal:
            sources_snapshot = await Get(Snapshot, PathGlobs(request.elements))
        else:
            sources_snapshot = request.snapshot  # only available on Batches for Fmt or Fix

        linter_address_str = subsystem.linter
        linter_address = await Get(
            Address,
            AddressInput,
            AddressInput.parse(linter_address_str, description_of_origin=f"ByoTool linter target"),
        )

        addresses = Addresses((linter_address,))
        addresses.expect_single()

        linter_targets = await Get(Targets, Addresses, addresses)

        linter = linter_targets[0]

        runnable_address_str = linter[AdhocToolRunnableField].value
        runnable_address = await Get(
            Address,
            AddressInput,
            AddressInput.parse(
                runnable_address_str,
                # Need to add a relative_to=addresses
                description_of_origin=f"ByoTool runnable target",
            ),
        )

        addresses = Addresses((runnable_address,))
        addresses.expect_single()

        runnable_targets = await Get(Targets, Addresses, addresses)

        target = runnable_targets[0]

        environment_name = await Get(
            EnvironmentName, EnvironmentNameRequest, EnvironmentNameRequest.from_target(target)
        )

        field_sets = await Get(
            FieldSetsPerTarget, FieldSetsPerTargetRequest(RunFieldSet, runnable_targets)
        )

        run_field_set: RunFieldSet = field_sets.field_sets[0]

        run_request = await Get(
            RunInSandboxRequest, {environment_name: EnvironmentName, run_field_set: RunFieldSet}
        )

        execution_environment = await Get(
            ResolvedExecutionDependencies,
            ResolveExecutionDependenciesRequest(
                target.address,
                execution_dependencies=linter[AdhocToolExecutionDependenciesField].value,
                runnable_dependencies=linter[AdhocToolRunnableDependenciesField].value,
            ),
        )

        dependencies_digest = execution_environment.digest
        runnable_dependencies = execution_environment.runnable_dependencies

        extra_env: dict[str, str] = dict(run_request.extra_env or {})
        extra_path = extra_env.pop("PATH", None)

        extra_sandbox_contents = []

        extra_sandbox_contents.append(
            ExtraSandboxContents(
                EMPTY_DIGEST,
                extra_path,
                run_request.immutable_input_digests or FrozenDict(),
                run_request.append_only_caches or FrozenDict(),
                run_request.extra_env or FrozenDict(),
            )
        )

        if runnable_dependencies:
            extra_sandbox_contents.append(
                ExtraSandboxContents(
                    EMPTY_DIGEST,
                    f"{{chroot}}/{runnable_dependencies.path_component}",
                    runnable_dependencies.immutable_input_digests,
                    runnable_dependencies.append_only_caches,
                    runnable_dependencies.extra_env,
                )
            )

        merged_extras = await Get(
            ExtraSandboxContents, MergeExtraSandboxContents(tuple(extra_sandbox_contents))
        )
        extra_env = dict(merged_extras.extra_env)
        if merged_extras.path:
            extra_env["PATH"] = merged_extras.path

        input_digest = await Get(
            Digest, MergeDigests((dependencies_digest, run_request.digest, sources_snapshot.digest))
        )

        cmd_args = linter[AdhocToolArgumentsField].value or ()

        append_only_caches = {
            **merged_extras.append_only_caches,
        }

        proc = Process(
            argv=tuple(run_request.args + cmd_args + sources_snapshot.files),
            description="Running byotool",
            input_digest=input_digest,
            append_only_caches=append_only_caches,
            immutable_input_digests=FrozenDict.frozen(merged_extras.immutable_input_digests),
            env=FrozenDict(extra_env),
            output_files=goal.output_files_to_read(request),
        )

        proc_result = await Get(FallibleProcessResult, Process, proc)
        output = await Get(Snapshot, Digest, proc_result.output_digest)

        return goal.create_result(request, process_result=proc_result, output=output)

    namespace = dict(locals())

    return [
        *collect_rules(namespace),
        *ByoToolRequest.rules(),
    ]
