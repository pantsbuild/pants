from dataclasses import dataclass

from pants.core.goals.lint import LintTargetsRequest, LintResult
from pants.core.target_types import FileSourceField
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.system_binaries import BinaryPathRequest, SEARCH_PATHS, BinaryPaths, BinaryShimsRequest, \
    BinaryShims
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import rule, collect_rules
from pants.engine.target import FieldSet, Target
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel


def shellcheck_rules():
    class ByoLintShellcheck(Subsystem):
        options_scope="shellcheck"
        skip=SkipOption("lint")
        name="Shellcheck"
        help="non-template shellcheck"


    @dataclass(frozen=True)
    class ByoLintShellcheckFieldSet(FieldSet):
        required_fields = (FileSourceField,)
        source: FileSourceField

        @classmethod
        def opt_out(cls, tgt: Target) -> bool:
            source = tgt.get(FileSourceField).value
            return not any(source.endswith(ext) for ext in [".sh"])

    class ByoLintShellcheckRequest(LintTargetsRequest):
        tool_subsystem=ByoLintShellcheck
        partitioner_type=PartitionerType.DEFAULT_SINGLE_PARTITION
        field_set_type=ByoLintShellcheckFieldSet

    @rule
    async def run_ByoLintShellcheck(
            request: ByoLintShellcheckRequest.Batch,
            complete_env: CompleteEnvironmentVars,
    ) -> LintResult:

        sources = await Get(
            SourceFiles,
            SourceFilesRequest(field_set.source for field_set in request.elements),
        )

        binary_request = BinaryPathRequest(binary_name="shellcheck", search_path=SEARCH_PATHS)
        paths = await Get(BinaryPaths, BinaryPathRequest, binary_request)

        import pantsdebug; pantsdebug.settrace_5678()
        input_digest = sources.snapshot.digest

        import pantsdebug; pantsdebug.settrace_5678()
        process_result = await Get(
            FallibleProcessResult,
            Process(
                argv=(paths.first_path.path, *sources.files),
                input_digest=input_digest,
                description=f"Run non-templated Shellcheck {paths.first_path.path}",
                level=LogLevel.INFO,
                # env={**complete_env}
            ),
        )
        return LintResult.create(request, process_result)

    namespace = dict(locals())
    return [
        *collect_rules(namespace),
        *ByoLintShellcheckRequest.rules()
    ]


def markdownlint_rules():
    class ByoLintMardkownLint(Subsystem):
        options_scope="markdownlint"
        skip=SkipOption("lint")
        name="Markdownlint"
        help="non-template markdownlint"


    @dataclass(frozen=True)
    class ByoLintMardkownLintFieldSet(FieldSet):
        required_fields = (FileSourceField,)
        source: FileSourceField

        @classmethod
        def opt_out(cls, tgt: Target) -> bool:
            source = tgt.get(FileSourceField).value
            return not any(source.endswith(ext) for ext in [".md"])

    class ByoLintMardkownLintRequest(LintTargetsRequest):
        tool_subsystem=ByoLintMardkownLint
        partitioner_type=PartitionerType.DEFAULT_SINGLE_PARTITION
        field_set_type=ByoLintMardkownLintFieldSet

    @rule
    async def run_ByoLintMardkownLint(
            request: ByoLintMardkownLintRequest.Batch,
            complete_env: CompleteEnvironmentVars,
    ) -> LintResult:

        sources = await Get(
            SourceFiles,
            SourceFilesRequest(field_set.source for field_set in request.elements),
        )

        binary_request = BinaryPathRequest(binary_name="markdownlint", search_path=SEARCH_PATHS)
        paths = await Get(BinaryPaths, BinaryPathRequest, binary_request)

        tools = ["node"]
        tool_resolution_request = BinaryShimsRequest.for_binaries(
            *tools, rationale="Needed for node", search_path=SEARCH_PATHS
        )
        resolved_tools = await Get(
            BinaryShims, BinaryShimsRequest, tool_resolution_request
        )

        import pantsdebug; pantsdebug.settrace_5678(True)
        input_digest = sources.snapshot.digest

        import pantsdebug; pantsdebug.settrace_5678()
        process_result = await Get(
            FallibleProcessResult,
            Process(
                argv=(paths.first_path.path, *sources.files),
                input_digest=input_digest,
                description=f"Run non-templated MardkownLint {paths.first_path.path}",
                level=LogLevel.INFO,
                env={'PATH': resolved_tools.path_component},
                immutable_input_digests=resolved_tools.immutable_input_digests,
            ),
        )
        return LintResult.create(request, process_result)

    namespace = dict(locals())
    return [
        *collect_rules(namespace),
        *ByoLintMardkownLintRequest.rules()
    ]
