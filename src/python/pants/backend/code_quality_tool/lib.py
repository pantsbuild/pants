# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.core.goals.multi_tool_goal_helper import SkippableSubsystem
from typing import ClassVar, Type, Mapping, Iterable

from pants.core.goals.fix import FixResult
from pants.core.goals.fmt import FmtFilesRequest, FmtResult
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
    Targets, StringField, SpecialCasedDependencies, FieldSet,
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


# class GoalSupport:
#     goal: str
#     request_superclass: Type[LintFilesRequest]
#     skippable: list[str]
#     result_class: type
#
#     @classmethod
#     def create_result(cls, request, process_result, output):
#         raise NotImplementedError
#
#     @classmethod
#     def output_files_to_read(cls, request: LintFilesRequest.Batch):
#         raise NotImplementedError
#
#
# class LintGoalSupport(GoalSupport):
#     goal = "lint"
#     request_superclass = LintFilesRequest
#     skippable = ["lint"]
#     result_class = LintResult
#
#     @classmethod
#     def create_result(cls, request, process_result, output):
#         return LintResult.create(request, process_result)
#
#     @classmethod
#     def output_files_to_read(cls, request: LintFilesRequest.Batch):
#         return None
#
#
# class FmtGoalSupport(GoalSupport):
#     goal = "fmt"
#     request_superclass = FmtFilesRequest
#     skippable = ["lint", "fmt"]
#     result_class = FixResult
#
#     @classmethod
#     def create_result(cls, request, process_result, output):
#         return FixResult(
#             input=request.snapshot,
#             output=output,
#             stdout=Simplifier().simplify(process_result.stdout),
#             stderr=Simplifier().simplify(process_result.stderr),
#             tool_name=request.tool_name,
#         )
#
#     @classmethod
#     def output_files_to_read(cls, request: FmtFilesRequest.Batch):
#         return request.files


@dataclass(frozen=True)
class CodeQualityToolAddressString:
    address: str


@dataclass(frozen=True)
class CodeQualityTool:
    runnable_address_str: str
    args: tuple[str, ...]
    execution_dependencies: tuple[str, ...]
    file_glob_include: tuple[str, ...]
    file_glob_exclude: tuple[str, ...]


@rule
async def find_code_quality_tool(request: CodeQualityToolAddressString) -> CodeQualityTool:
    linter_address_str = request.address
    linter_address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(linter_address_str, description_of_origin=f"ByoTool linter target"),
    )

    addresses = Addresses((linter_address,))
    addresses.expect_single()

    linter_targets = await Get(Targets, Addresses, addresses)
    target = linter_targets[0]
    runnable_address_str = target[CodeQualityToolRunnableField].value
    if not runnable_address_str:
        raise Exception(f"Must supply a value for `runnable` for {request.address}.")

    return CodeQualityTool(
        runnable_address_str=runnable_address_str,
        execution_dependencies=target[CodeQualityToolExecutionDependenciesField].value or (),
        args=target[CodeQualityToolArgumentsField].value or (),
        file_glob_include=target[CodeQualityToolFileGlobIncludeField].value or (),
        file_glob_exclude=target[CodeQualityToolFileGlobExcludeField].value or (),
    )


@dataclass(frozen=True)
class CodeQualityToolBatchRunner:
    digest: Digest
    args: tuple[str, ...]
    extra_env: Mapping[str, str]
    append_only_caches: Mapping[str, str]
    immutable_input_digests: Mapping[str, Digest]



@dataclass(frozen=True)
class CodeQualityToolBatch:
    runner: CodeQualityToolBatchRunner
    sources_snapshot: Snapshot
    output_files: tuple[str, ...]

@rule
async def process_files(batch: CodeQualityToolBatch) -> FallibleProcessResult:
    runner = batch.runner

    input_digest = await Get(
        Digest, MergeDigests((runner.digest, batch.sources_snapshot.digest))
    )

    result = await Get(
        FallibleProcessResult,
        Process(
            argv=tuple(runner.args + batch.sources_snapshot.files),
            description="Running code quality tool",
            input_digest=input_digest,
            append_only_caches=runner.append_only_caches,
            immutable_input_digests=FrozenDict.frozen(runner.immutable_input_digests),
            env=FrozenDict(runner.extra_env),
            output_files=batch.output_files,
        ))
    return result


@rule
async def hydrate_code_quality_tool(request: CodeQualityToolAddressString) -> CodeQualityToolBatchRunner:
    cqt = await Get(CodeQualityTool, CodeQualityToolAddressString, request)

    runnable_address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(
            cqt.runnable_address_str,
            # Need to add a relative_to=addresses
            description_of_origin=f"Code Quality Tool runnable target",
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
            execution_dependencies=cqt.execution_dependencies,
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

    return CodeQualityToolBatchRunner(
        digest=digest,
        args=run_request.args + tuple(cqt.args),
        extra_env=FrozenDict(extra_env),
        append_only_caches=merged_extras.append_only_caches,
        immutable_input_digests=merged_extras.immutable_input_digests,
    )


@dataclass
class CodeQualityToolRuleBuilder:
    goal: str
    target: str
    name: str
    scope: str

    # def supported_goal(self) -> Type[GoalSupport]:
    #     if self.goal == "fmt":
    #         return FmtGoalSupport
    #     elif self.goal == "lint":
    #         return LintGoalSupport
    #     else:
    #         raise ValueError(f"Unknown goal {self.goal}")

    def _build_lint_rules(self):
        class ByoTool(Subsystem):
            options_scope = self.scope
            name = self.name
            help = f"{self.goal.capitalize()} with {self.name}. Tool defined in {self.target}"

            skip = SkipOption("lint")

        class ByoToolRequest(LintFilesRequest):
            tool_subsystem = ByoTool

        @rule(canonical_name_suffix=self.scope)
        async def partition_inputs(
            request: ByoToolRequest.PartitionRequest, subsystem: ByoTool
        ) -> Partitions:
            if subsystem.skip:
                return Partitions()

            cqt = await Get(CodeQualityTool, CodeQualityToolAddressString(address=self.target))

            matching_filepaths = FilespecMatcher(
                includes=cqt.file_glob_include,
                excludes=cqt.file_glob_exclude,
            ).matches(request.files)

            return Partitions.single_partition(sorted(matching_filepaths))

        @rule(canonical_name_suffix=self.scope)
        async def run_byotool(request: ByoToolRequest.Batch) -> LintResult:
            sources_snapshot = await Get(Snapshot, PathGlobs(request.elements))

            code_quality_tool_runner = await Get(
                CodeQualityToolBatchRunner,
                CodeQualityToolAddressString(address=self.target))

            proc_result = await Get(
                FallibleProcessResult,
                CodeQualityToolBatch(
                    runner=code_quality_tool_runner,
                    sources_snapshot=sources_snapshot,
                    output_files=(),
                ))

            return LintResult.create(request, process_result=proc_result)

        namespace = dict(locals())

        return [
            *collect_rules(namespace),
            *ByoToolRequest.rules(),
        ]

    def _build_fmt_rules(self):
        class ByoTool(Subsystem):
            options_scope = self.scope
            name = self.name
            help = f"{self.goal.capitalize()} with {self.name}. Tool defined in {self.target}"

            skip = SkipOption("lint", "fmt")

        class ByoToolRequest(FmtFilesRequest):
            tool_subsystem = ByoTool

        @rule(canonical_name_suffix=self.scope)
        async def partition_inputs(
            request: ByoToolRequest.PartitionRequest, subsystem: ByoTool
        ) -> Partitions:
            if subsystem.skip:
                return Partitions()

            cqt = await Get(CodeQualityTool, CodeQualityToolAddressString(address=self.target))

            matching_filepaths = FilespecMatcher(
                includes=cqt.file_glob_include,
                excludes=cqt.file_glob_exclude,
            ).matches(request.files)

            return Partitions.single_partition(sorted(matching_filepaths))

        @rule(canonical_name_suffix=self.scope)
        async def run_byotool(request: ByoToolRequest.Batch) -> FmtResult:
            sources_snapshot = request.snapshot  # only available on Batches for Fmt or Fix

            code_quality_tool_runner = await Get(
                CodeQualityToolBatchRunner,
                CodeQualityToolAddressString(address=self.target))

            proc_result = await Get(
                FallibleProcessResult,
                CodeQualityToolBatch(
                    runner=code_quality_tool_runner,
                    sources_snapshot=sources_snapshot,
                    output_files=request.files,
                ))

            output = await Get(Snapshot, Digest, proc_result.output_digest)

            return FmtResult(
                input=request.snapshot,
                output=output,
                stdout=Simplifier().simplify(proc_result.stdout),
                stderr=Simplifier().simplify(proc_result.stderr),
                tool_name=request.tool_name,
            )

        namespace = dict(locals())

        return [
            *collect_rules(namespace),
            *ByoToolRequest.rules(),
        ]

    def build_rules(self):
        rules = [
            find_code_quality_tool,
            process_files,
            hydrate_code_quality_tool,
        ]

        if self.goal == 'fmt':
            rules.extend(self._build_fmt_rules())
        elif self.goal == 'lint':
            rules.extend(self._build_lint_rules())
        else:
            raise ValueError(f'Unsupported goal for code quality tool: {self.goal}')

        return rules

    # def build_rules_old(self):
    #     goal = self.supported_goal()
    #
    #     class ByoTool(Subsystem):
    #         options_scope = self.scope
    #         name = self.name
    #         help = f"{self.goal.capitalize()} with {self.name}. Tool defined in {self.target}"
    #
    #         skip = SkipOption(*goal.skippable)
    #
    #     class ByoToolRequest(goal.request_superclass):
    #         tool_subsystem = ByoTool
    #
    #     @rule(canonical_name_suffix=self.scope)
    #     async def partition_inputs(
    #         request: ByoToolRequest.PartitionRequest, subsystem: ByoTool
    #     ) -> Partitions[str, PartitionMetadata]:
    #         if subsystem.skip:
    #             return Partitions()
    #
    #         cqt = await Get(CodeQualityTool, CodeQualityToolAddressString(address=self.target))
    #
    #         matching_filepaths = FilespecMatcher(
    #             includes=cqt.file_glob_include,
    #             excludes=cqt.file_glob_exclude,
    #         ).matches(request.files)
    #
    #         return Partitions.single_partition(sorted(matching_filepaths))
    #
    #     result_class = goal.result_class
    #
    #     @rule(canonical_name_suffix=self.scope)
    #     async def run_byotool(request: ByoToolRequest.Batch) -> result_class:
    #
    #         if goal is LintGoalSupport:
    #             sources_snapshot = await Get(Snapshot, PathGlobs(request.elements))
    #         else:
    #             sources_snapshot = request.snapshot  # only available on Batches for Fmt or Fix
    #
    #         code_quality_tool_runner = await Get(
    #             CodeQualityToolBatchRunner,
    #             CodeQualityToolAddressString(address=self.target))
    #
    #         proc_result = await Get(
    #             FallibleProcessResult,
    #             CodeQualityToolBatch(
    #                 runner=code_quality_tool_runner,
    #                 sources_snapshot=sources_snapshot,
    #                 output_files=goal.output_files_to_read(request),
    #             ))
    #
    #         output = await Get(Snapshot, Digest, proc_result.output_digest)
    #
    #         return goal.create_result(request, process_result=proc_result, output=output)
    #
    #     namespace = dict(locals())
    #
    #     return [
    #         find_code_quality_tool,
    #         process_files,
    #         hydrate_code_quality_tool,
    #         *collect_rules(namespace),
    #         *ByoToolRequest.rules(),
    #     ]
