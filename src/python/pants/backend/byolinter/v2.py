from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPexProcess, PexProcess
from pants.core.goals.lint import LintFilesRequest, LintResult
from pants.core.util_rules.partitions import Partitions, Partition, PartitionMetadata
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import FilespecMatcher, Snapshot, Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import rule, collect_rules
from pants.option.option_types import SkipOption, StrOption
from pants.util.logging import LogLevel

#
# confs2 = [
#     ByoLinter2(
#         options_scope='flake8',
#         name="Flake8"
#     executable = PythonTool(
#     main=ConsoleScript("flake8"),
#     default_requirements=["flake8>=5.0.4,<7"],
#     default_lockfile_resource=("pants.backend.python.lint.flake8", "flake8.lock"),
# )
# )
# ]
#
# @dataclass
# class Provided:
#     command: str
#     tools: List[str] = None
#
#
# @dataclass
# class PythonTool:
#
#
# @dataclass
# class ByoLinter2:
#     options_scope: str
#     name: str
#     help: str
#     executable: Provided |
#     file_extensions: List[str]
#     tools: List[str] = None
#
#     def rules(self):
#         return build(self)

class ByoFlake8Subsystem(PythonToolBase):
    options_scope = "byo_flake8"
    name = "ByoFlake8"
    help = "The Flake8 Python linter (https://flake8.pycqa.org/)."

    default_main = ConsoleScript("flake8")  # type is MainSpecification
    default_requirements = ["flake8>=5.0.4,<7"]

    default_lockfile_resource = ("pants.backend.byolinter.tools.flake8", "byo_flake8.lock")
    skip = SkipOption("lint")

    file_glob_include = ["**/*.py"]

    register_interpreter_constraints = True

    install_from_resolve = "byo_flake8"

    file_glob_exclude = []
    # # We add config discovery later
    # _interpreter_constraints =


class ByoFlake8Request(LintFilesRequest):
    tool_subsystem = ByoFlake8Subsystem


@rule
async def partition_inputs(
    request: ByoFlake8Request.PartitionRequest, subsystem: ByoFlake8Subsystem
) -> Partitions[str, PartitionMetadata]:
    if subsystem.skip:
        return Partitions()

    matching_filepaths = FilespecMatcher(
        includes=subsystem.file_glob_include, excludes=subsystem.file_glob_exclude
    ).matches(request.files)

    return Partitions.single_partition(sorted(matching_filepaths))

@rule
async def run_byolint(
        request: ByoFlake8Request.Batch[str, PartitionMetadata],
        subsystem: ByoFlake8Subsystem
) -> LintResult:
    import pantsdebug; pantsdebug.settrace_5678(True)
    pex_request = subsystem.to_pex_request()
    byo_bin = await Get(Pex, PexRequest, pex_request)
    snapshot = await Get(Snapshot, PathGlobs(request.elements))
    import pantsdebug; pantsdebug.settrace_5678()

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


def rules():
    return [
        *collect_rules(),
        *ByoFlake8Request.rules()
    ]