from dataclasses import dataclass
from typing import List

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import MainSpecification
from pants.backend.python.util_rules.pex import Pex, PexRequest, PexProcess
from pants.core.goals.lint import LintTargetsRequest, LintResult, LintFilesRequest
from pants.core.target_types import FileSourceField
from pants.core.util_rules.partitions import PartitionerType, Partitions, PartitionMetadata
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.system_binaries import SEARCH_PATHS, BinaryPathRequest, BinaryPaths, BinaryShimsRequest, \
    BinaryShims
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import FilespecMatcher, Snapshot, Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel



class Executable:
    pass


@dataclass
class SystemBinaryExecutable(Executable):
    command: str
    tools: List[str] = None


@dataclass
class PythonToolExecutable(Executable):
    main: MainSpecification
    requirements: list[str]
    resolve: str


@dataclass
class ByoLinter:
    options_scope: str
    name: str
    help: str
    executable: Executable
    file_glob_include: List[str]
    file_glob_exclude: List[str]

    def rules(self):
        return build(self)


def build(conf: ByoLinter):
    assert conf.options_scope.isidentifier(), "The options scope must be a valid python identifier"

    if isinstance(conf.executable, SystemBinaryExecutable):
        subsystem_cls = type(Subsystem)(f'ByoLint_{conf.options_scope}_Subsystem', (Subsystem,), dict(
            options_scope=conf.options_scope,
            skip=SkipOption("lint"),
            name=conf.name,
            help=conf.help,
            _dynamic_subsystem=True,
        ))
    elif isinstance(conf.executable, PythonToolExecutable):
        subsystem_cls = type(PythonToolBase)(f'ByoLint_{conf.options_scope}_Subsystem', (PythonToolBase,), dict(
            options_scope=conf.options_scope,
            skip=SkipOption("lint"),
            name=conf.name,
            help=conf.help,
            _dynamic_subsystem=True,
            default_main=conf.executable.main,
            default_requirements=conf.executable.requirements,
            default_lockfile_resource=("pants.backend.byolinter.SHOULDNEVERBEUSED", "NOTNEEDED.lock"),
            register_interpreter_constraints=True,
            install_from_resolve=conf.executable.resolve,
        ))

    subsystem_cls.__module__ = __name__

    lint_files_req_cls = type(LintFilesRequest)(f'ByoLint_{conf.options_scope}_Request', (LintFilesRequest,), dict(
        tool_subsystem=subsystem_cls,
    ))
    lint_files_req_cls.__module__ = __name__

    @rule(canonical_name_suffix=conf.options_scope)
    async def partition_inputs(
            request: lint_files_req_cls.PartitionRequest,
            subsystem: subsystem_cls
    ) -> Partitions[str, PartitionMetadata]:
        if subsystem.skip:
            return Partitions()

        matching_filepaths = FilespecMatcher(
            includes=conf.file_glob_include, excludes=conf.file_glob_exclude
        ).matches(request.files)

        return Partitions.single_partition(sorted(matching_filepaths))

    if isinstance(conf.executable, SystemBinaryExecutable):
        @rule(canonical_name_suffix=conf.options_scope)
        async def run_ByoLint_from_bin_executable(
                request: lint_files_req_cls.Batch,
        ) -> LintResult:

            executable = conf.executable

            sources_snapshot = await Get(Snapshot, PathGlobs(request.elements))

            search_paths = SEARCH_PATHS

            binary_request = BinaryPathRequest(binary_name=executable.command, search_path=search_paths)
            command_paths = await Get(BinaryPaths, BinaryPathRequest, binary_request)
            command_path = command_paths.first_path.path

            tools_path_env = {}
            tools_input_digests = FrozenDict()

            if executable.tools:
                tool_resolution_request = BinaryShimsRequest.for_binaries(
                    *executable.tools,
                    rationale=f"Needed for {conf.options_scope} linter",
                    search_path=SEARCH_PATHS
                )
                resolved_tools = await Get(
                    BinaryShims, BinaryShimsRequest, tool_resolution_request
                )

                tools_path_env = {'PATH': resolved_tools.path_component}
                tools_input_digests = resolved_tools.immutable_input_digests

            input_digest = sources_snapshot.digest

            import pantsdebug; pantsdebug.settrace_5678()
            process_result = await Get(
                FallibleProcessResult,
                Process(
                    argv=(command_path, *sources_snapshot.files),
                    input_digest=input_digest,
                    description=f"Run {conf.name}",
                    level=LogLevel.INFO,
                    env=tools_path_env,
                    immutable_input_digests=tools_input_digests,
                ),
            )
            return LintResult.create(request, process_result)

    elif isinstance(conf.executable, PythonToolExecutable):
        @rule(canonical_name_suffix=conf.options_scope)
        async def run_byolint(
                request: lint_files_req_cls.Batch,
                subsystem: subsystem_cls
        ) -> LintResult:
            pex_request = subsystem.to_pex_request()
            byo_bin = await Get(Pex, PexRequest, pex_request)
            snapshot = await Get(Snapshot, PathGlobs(request.elements))
            import pantsdebug;
            pantsdebug.settrace_5678()

            input_digest = await Get(
                Digest,
                MergeDigests((snapshot.digest, byo_bin.digest))
            )

            process = PexProcess(
                byo_bin,
                argv=snapshot.files,
                input_digest=input_digest,
                description=f"Run byo_flake8",
                level=LogLevel.INFO
            )
            process_result = await Get(FallibleProcessResult, PexProcess, process)
            return LintResult.create(request, process_result)

    namespace = dict(locals())

    return [
        *collect_rules(namespace),
        *lint_files_req_cls.rules()
    ]



