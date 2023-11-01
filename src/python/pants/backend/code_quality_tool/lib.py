# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import ClassVar, Type, Mapping, Iterable

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
    Targets, StringField, SpecialCasedDependencies,
)
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.strutil import Simplifier, help_text


class CodeQualityToolFileGlobIncludeField(StringSequenceField):
    alias: ClassVar[str] = "file_glob_include"
    required = True


class CodeQualityToolFileGlobExcludeField(StringSequenceField):
    alias: ClassVar[str] = "file_glob_exclude"
    required = False
    default = ()

class CodeQualityToolRunnableField(StringField):
    alias: ClassVar[str] = "runnable"
    required = True
    help = help_text(
        lambda: f"""
        Address to a target that can be invoked by the `run` goal (and does not set
        `run_in_sandbox_behavior=NOT_SUPPORTED`). This will be executed along with any arguments
        specified by `{CodeQualityToolArgumentsField.alias}`, in a sandbox with that target's transitive
        dependencies, along with the transitive dependencies specified by
        `{CodeQualityToolExecutionDependenciesField.alias}`.
        """
    )

class CodeQualityToolArgumentsField(StringSequenceField):
    alias: ClassVar[str] = "args"
    default = ()
    help = help_text(
        lambda: f"""
        Extra arguments to pass into the `{CodeQualityToolRunnableField.alias}` field
        before the list of source files
        """
    )


class CodeQualityToolExecutionDependenciesField(SpecialCasedDependencies):
    alias: ClassVar[str] = "execution_dependencies"
    required = False
    default = None

    help = help_text(
        lambda: f"""
        Additional dependencies that need to be available when running the tool.
        Typically used to point to config files.
        """
    )


class CodeQualityToolTarget(Target):
    alias: ClassVar[str] = "code_quality_tool"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        CodeQualityToolRunnableField,
        CodeQualityToolArgumentsField,
        CodeQualityToolExecutionDependenciesField,
        CodeQualityToolFileGlobIncludeField,
        CodeQualityToolFileGlobExcludeField,
    )


class SupportedGoal:
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


class LintGoal(SupportedGoal):
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


class FmtGoal(SupportedGoal):
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


@dataclass(frozen=True)
class HydratedCodeQualityToolRequest:
    address: str


@dataclass(frozen=True)
class HydratedCodeQualityTool:
    environment_name: EnvironmentName
    run_field_set: RunFieldSet
    runnable_target: Target
    run_request: RunInSandboxRequest
    merged_extras: ExtraSandboxContents
    dependencies_digest: Digest
    extra_env: Mapping[str, str]
    digest: Digest
    cmd_args: tuple[str, ...]


@dataclass(frozen=True)
class CodeQualityToolBatch:
    tool: HydratedCodeQualityTool
    sources_snapshot: Snapshot
    output_files: tuple[str, ...]

@rule
async def process_files(batch: CodeQualityToolBatch) -> FallibleProcessResult:
    tool = batch.tool

    input_digest = await Get(
        Digest, MergeDigests((tool.digest, batch.sources_snapshot.digest))
    )

    cmd_args = tool.cmd_args

    append_only_caches = {
        **tool.merged_extras.append_only_caches,
    }

    Process(
        argv=tuple(tool.run_request.args + cmd_args + batch.sources_snapshot.files),
        description="Running byotool",
        input_digest=input_digest,
        append_only_caches=append_only_caches,
        immutable_input_digests=FrozenDict.frozen(tool.merged_extras.immutable_input_digests),
        env=FrozenDict(tool.extra_env),
        output_files=batch.output_files,
    )

    result = await Get(
        FallibleProcessResult,
        Process(
            argv=tuple(tool.run_request.args + cmd_args + batch.sources_snapshot.files),
            description="Running byotool",
            input_digest=input_digest,
            append_only_caches=append_only_caches,
            immutable_input_digests=FrozenDict.frozen(tool.merged_extras.immutable_input_digests),
            env=FrozenDict(tool.extra_env),
            output_files=batch.output_files,
        ))
    return result


@rule
async def hydrate_code_quality_tool(request: HydratedCodeQualityToolRequest) -> HydratedCodeQualityTool:
    linter_address_str = request.address
    linter_address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(linter_address_str, description_of_origin=f"ByoTool linter target"),
    )

    addresses = Addresses((linter_address,))
    addresses.expect_single()

    linter_targets = await Get(Targets, Addresses, addresses)

    linter = linter_targets[0]

    runnable_address_str = linter[CodeQualityToolRunnableField].value
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


    field_sets = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(RunFieldSet, runnable_targets)
    )

    environment_name = await Get(
        EnvironmentName, EnvironmentNameRequest, EnvironmentNameRequest.from_target(target)
    )

    run_field_set: RunFieldSet = field_sets.field_sets[0]

    run_request = await Get(
        RunInSandboxRequest, {environment_name: EnvironmentName, run_field_set: RunFieldSet}
    )

    execution_environment = await Get(
        ResolvedExecutionDependencies,
        ResolveExecutionDependenciesRequest(
            target.address,
            execution_dependencies=linter[CodeQualityToolExecutionDependenciesField].value,
            runnable_dependencies=None,
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

    digest = await Get(Digest, MergeDigests((dependencies_digest, run_request.digest)))

    cmd_args = linter[CodeQualityToolArgumentsField].value or ()

    return HydratedCodeQualityTool(
        run_field_set=run_field_set,
        environment_name=environment_name,
        runnable_target=target,
        run_request=run_request,
        merged_extras=merged_extras,
        dependencies_digest=dependencies_digest,
        extra_env=FrozenDict(extra_env),
        digest=digest,
        cmd_args=tuple(cmd_args),
    )


@dataclass
class CodeQualityToolRuleBuilder:
    goal: str
    target: str
    name: str
    scope: str

    @property
    def _goal(self) -> SupportedGoal:
        if self.goal == "fmt":
            return FmtGoal
        elif self.goal == "lint":
            return LintGoal
        else:
            raise ValueError(f"Unknown goal {self.goal}")

    def build_rules(self):
        goal = self._goal

        class ByoTool(Subsystem):
            options_scope = self.scope
            name = self.name
            help = f"{self.goal.capitalize()} with {self.name}. Tool defined in {self.target}"

            skip = SkipOption(*goal.skippable)
            linter = self.target

        request_superclass = goal.request_superclass

        class ByoToolRequest(request_superclass):
            tool_subsystem = ByoTool

        @rule(canonical_name_suffix=self.scope)
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
                includes=linter[CodeQualityToolFileGlobIncludeField].value,
                excludes=linter[CodeQualityToolFileGlobExcludeField].value,
            ).matches(request.files)

            return Partitions.single_partition(sorted(matching_filepaths))

        result_class = goal.result_class

        @rule(canonical_name_suffix=self.scope)
        async def run_byotool(request: ByoToolRequest.Batch, subsystem: ByoTool) -> result_class:

            if goal is LintGoal:
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

            code_quality_tool = await Get(HydratedCodeQualityTool,
                      HydratedCodeQualityToolRequest(address=subsystem.linter))

            proc_result = await Get(
                FallibleProcessResult,
                CodeQualityToolBatch(
                    tool=code_quality_tool,
                    sources_snapshot=sources_snapshot,
                    output_files=goal.output_files_to_read(request),
                ))

            output = await Get(Snapshot, Digest, proc_result.output_digest)

            return goal.create_result(request, process_result=proc_result, output=output)

        namespace = dict(locals())

        return [
            process_files,
            hydrate_code_quality_tool,
            *collect_rules(namespace),
            *ByoToolRequest.rules(),
        ]
