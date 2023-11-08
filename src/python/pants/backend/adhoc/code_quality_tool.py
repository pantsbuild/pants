# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import ClassVar, Iterable, Mapping

from pants.core.goals.fix import Fix, FixFilesRequest, FixResult
from pants.core.goals.fmt import Fmt, FmtFilesRequest, FmtResult
from pants.core.goals.lint import Lint, LintFilesRequest, LintResult
from pants.core.goals.run import RunFieldSet, RunInSandboxRequest
from pants.core.util_rules.adhoc_process_support import (
    ExtraSandboxContents,
    MergeExtraSandboxContents,
    ResolvedExecutionDependencies,
    ResolveExecutionDependenciesRequest,
)
from pants.core.util_rules.adhoc_process_support import rules as adhoc_process_support_rules
from pants.core.util_rules.environments import EnvironmentNameRequest
from pants.core.util_rules.partitions import Partitions
from pants.engine.addresses import Addresses
from pants.engine.environment import EnvironmentName
from pants.engine.fs import PathGlobs
from pants.engine.goal import Goal
from pants.engine.internals.native_engine import (
    EMPTY_DIGEST,
    Address,
    AddressInput,
    Digest,
    FilespecMatcher,
    MergeDigests,
    Snapshot,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    SpecialCasedDependencies,
    StringField,
    StringSequenceField,
    Target,
    Targets,
)
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.strutil import Simplifier, help_text


class CodeQualityToolFileGlobIncludeField(StringSequenceField):
    alias: ClassVar[str] = "file_glob_include"
    required = True
    help = help_text(
        """
        Globs that identify files that can be processed by this tool

        A file matching any of the supplied globs is eligible for processing.
        Example: ["**/*.py"]
        """
    )


class CodeQualityToolFileGlobExcludeField(StringSequenceField):
    alias: ClassVar[str] = "file_glob_exclude"
    required = False
    default = ()
    help = help_text(
        """
        Globs matching files that should not be processed by this tool
        """
    )


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
        """
        Additional dependencies that need to be available when running the tool.
        Typically used to point to config files.
        """
    )


class CodeQualityToolRunnableDependenciesField(SpecialCasedDependencies):
    alias: ClassVar[str] = "runnable_dependencies"
    required = False
    default = None

    help = help_text(
        lambda: f"""
        The runnable dependencies for this command.

        Dependencies specified here are those required to exist on the `PATH` to make the command
        complete successfully (interpreters specified in a `#!` command, etc). Note that these
        dependencies will be made available on the `PATH` with the name of the target.

        See also `{CodeQualityToolExecutionDependenciesField.alias}`.
        """
    )


class CodeQualityToolTarget(Target):
    alias: ClassVar[str] = "code_quality_tool"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        CodeQualityToolRunnableField,
        CodeQualityToolArgumentsField,
        CodeQualityToolExecutionDependenciesField,
        CodeQualityToolRunnableDependenciesField,
        CodeQualityToolFileGlobIncludeField,
        CodeQualityToolFileGlobExcludeField,
    )

    help = help_text(
        lambda: f"""
        Configure a runnable to use as a linter, fixer or formatter

        Example BUILD file:

            {CodeQualityToolTarget.alias}(
                {CodeQualityToolRunnableField.alias}=":flake8_req",
                {CodeQualityToolExecutionDependenciesField.alias}=[":config_file"],
                {CodeQualityToolFileGlobIncludeField.alias}=["**/*.py"],
            )
        """
    )


@dataclass(frozen=True)
class CodeQualityToolAddressString:
    address: str


@dataclass(frozen=True)
class CodeQualityTool:
    runnable_address_str: str
    args: tuple[str, ...]
    execution_dependencies: tuple[str, ...]
    runnable_dependencies: tuple[str, ...]
    file_glob_include: tuple[str, ...]
    file_glob_exclude: tuple[str, ...]
    target: Target


@rule
async def find_code_quality_tool(request: CodeQualityToolAddressString) -> CodeQualityTool:
    tool_address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(request.address, description_of_origin="code quality tool target"),
    )

    addresses = Addresses((tool_address,))
    addresses.expect_single()

    tool_targets = await Get(Targets, Addresses, addresses)
    target = tool_targets[0]
    runnable_address_str = target[CodeQualityToolRunnableField].value
    if not runnable_address_str:
        raise Exception(f"Must supply a value for `runnable` for {request.address}.")

    return CodeQualityTool(
        runnable_address_str=runnable_address_str,
        execution_dependencies=target[CodeQualityToolExecutionDependenciesField].value or (),
        runnable_dependencies=target[CodeQualityToolRunnableDependenciesField].value or (),
        args=target[CodeQualityToolArgumentsField].value or (),
        file_glob_include=target[CodeQualityToolFileGlobIncludeField].value or (),
        file_glob_exclude=target[CodeQualityToolFileGlobExcludeField].value or (),
        target=target,
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

    input_digest = await Get(Digest, MergeDigests((runner.digest, batch.sources_snapshot.digest)))

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
        ),
    )
    return result


@rule
async def hydrate_code_quality_tool(
    request: CodeQualityToolAddressString,
) -> CodeQualityToolBatchRunner:
    cqt = await Get(CodeQualityTool, CodeQualityToolAddressString, request)

    runnable_address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(
            cqt.runnable_address_str,
            relative_to=cqt.target.address.spec_path,
            description_of_origin=f"Runnable target for code quality tool {cqt.target.address.spec_path}",
        ),
    )

    addresses = Addresses((runnable_address,))
    addresses.expect_single()

    runnable_targets = await Get(Targets, Addresses, addresses)

    target = runnable_targets[0]

    run_field_sets, environment_name, execution_environment = await MultiGet(
        Get(FieldSetsPerTarget, FieldSetsPerTargetRequest(RunFieldSet, runnable_targets)),
        Get(EnvironmentName, EnvironmentNameRequest, EnvironmentNameRequest.from_target(target)),
        Get(
            ResolvedExecutionDependencies,
            ResolveExecutionDependenciesRequest(
                address=runnable_address,
                execution_dependencies=cqt.execution_dependencies,
                runnable_dependencies=cqt.runnable_dependencies,
            ),
        ),
    )

    run_field_set: RunFieldSet = run_field_sets.field_sets[0]

    run_request = await Get(
        RunInSandboxRequest, {environment_name: EnvironmentName, run_field_set: RunFieldSet}
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

    merged_extras, main_digest = await MultiGet(
        Get(ExtraSandboxContents, MergeExtraSandboxContents(tuple(extra_sandbox_contents))),
        Get(Digest, MergeDigests((dependencies_digest, run_request.digest))),
    )

    extra_env = dict(merged_extras.extra_env)
    if merged_extras.path:
        extra_env["PATH"] = merged_extras.path

    return CodeQualityToolBatchRunner(
        digest=main_digest,
        args=run_request.args + tuple(cqt.args),
        extra_env=FrozenDict(extra_env),
        append_only_caches=merged_extras.append_only_caches,
        immutable_input_digests=merged_extras.immutable_input_digests,
    )


_name_to_supported_goal = {g.name: g for g in (Lint, Fmt, Fix)}


class CodeQualityToolUnsupportedGoalError(Exception):
    """Raised when a rule builder is instantiated for an unrecognized or unsupported goal."""


@dataclass
class CodeQualityToolRuleBuilder:
    goal: str
    target: str
    name: str
    scope: str

    @property
    def goal_type(self) -> type[Goal]:
        return _name_to_supported_goal[self.goal]

    def __post_init__(self):
        if self.goal not in _name_to_supported_goal:
            raise CodeQualityToolUnsupportedGoalError(
                f"""goal must be one of {sorted(_name_to_supported_goal)}"""
            )

    def rules(self) -> Iterable[Rule]:
        if self.goal_type is Fmt:
            return self._build_fmt_rules()
        elif self.goal_type is Fix:
            return self._build_fix_rules()
        elif self.goal_type is Lint:
            return self._build_lint_rules()
        else:
            raise ValueError(f"Unsupported goal for code quality tool: {self.goal}")

    def _build_lint_rules(self) -> Iterable[Rule]:
        class CodeQualityToolInstance(Subsystem):
            options_scope = self.scope
            name = self.name
            help = f"{self.goal.capitalize()} with {self.name}. Tool defined in {self.target}"

            skip = SkipOption("lint")

        class CodeQualityProcessingRequest(LintFilesRequest):
            tool_subsystem = CodeQualityToolInstance

        @rule(canonical_name_suffix=self.scope)
        async def partition_inputs(
            request: CodeQualityProcessingRequest.PartitionRequest,
            subsystem: CodeQualityToolInstance,
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
        async def run_code_quality(request: CodeQualityProcessingRequest.Batch) -> LintResult:
            sources_snapshot = await Get(Snapshot, PathGlobs(request.elements))

            code_quality_tool_runner = await Get(
                CodeQualityToolBatchRunner, CodeQualityToolAddressString(address=self.target)
            )

            proc_result = await Get(
                FallibleProcessResult,
                CodeQualityToolBatch(
                    runner=code_quality_tool_runner,
                    sources_snapshot=sources_snapshot,
                    output_files=(),
                ),
            )

            return LintResult.create(request, process_result=proc_result)

        namespace = dict(locals())

        return [
            *collect_rules(namespace),
            *CodeQualityProcessingRequest.rules(),
        ]

    def _build_fmt_rules(self) -> Iterable[Rule]:
        class CodeQualityToolInstance(Subsystem):
            options_scope = self.scope
            name = self.name
            help = f"{self.goal.capitalize()} with {self.name}. Tool defined in {self.target}"

            skip = SkipOption("lint", "fmt")

        class CodeQualityProcessingRequest(FmtFilesRequest):
            tool_subsystem = CodeQualityToolInstance

        @rule(canonical_name_suffix=self.scope)
        async def partition_inputs(
            request: CodeQualityProcessingRequest.PartitionRequest,
            subsystem: CodeQualityToolInstance,
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
        async def run_code_quality(request: CodeQualityProcessingRequest.Batch) -> FmtResult:
            sources_snapshot = request.snapshot

            code_quality_tool_runner = await Get(
                CodeQualityToolBatchRunner, CodeQualityToolAddressString(address=self.target)
            )

            proc_result = await Get(
                FallibleProcessResult,
                CodeQualityToolBatch(
                    runner=code_quality_tool_runner,
                    sources_snapshot=sources_snapshot,
                    output_files=request.files,
                ),
            )

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
            *CodeQualityProcessingRequest.rules(),
        ]

    def _build_fix_rules(self) -> Iterable[Rule]:
        class CodeQualityToolInstance(Subsystem):
            options_scope = self.scope
            name = self.name
            help = f"{self.goal.capitalize()} with {self.name}. Tool defined in {self.target}"

            skip = SkipOption("lint", "fmt", "fix")

        class CodeQualityProcessingRequest(FixFilesRequest):
            tool_subsystem = CodeQualityToolInstance

        @rule(canonical_name_suffix=self.scope)
        async def partition_inputs(
            request: CodeQualityProcessingRequest.PartitionRequest,
            subsystem: CodeQualityToolInstance,
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
        async def run_code_quality(request: CodeQualityProcessingRequest.Batch) -> FixResult:
            sources_snapshot = request.snapshot

            code_quality_tool_runner = await Get(
                CodeQualityToolBatchRunner, CodeQualityToolAddressString(address=self.target)
            )

            proc_result = await Get(
                FallibleProcessResult,
                CodeQualityToolBatch(
                    runner=code_quality_tool_runner,
                    sources_snapshot=sources_snapshot,
                    output_files=request.files,
                ),
            )

            output = await Get(Snapshot, Digest, proc_result.output_digest)

            return FixResult(
                input=request.snapshot,
                output=output,
                stdout=Simplifier().simplify(proc_result.stdout),
                stderr=Simplifier().simplify(proc_result.stderr),
                tool_name=request.tool_name,
            )

        namespace = dict(locals())

        return [
            *collect_rules(namespace),
            *CodeQualityProcessingRequest.rules(),
        ]


def base_rules():
    return [
        *collect_rules(),
        *adhoc_process_support_rules(),
    ]
