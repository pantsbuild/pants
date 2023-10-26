from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.core.goals.lint import LintFilesRequest, LintResult
from pants.core.goals.run import RunFieldSet, RunInSandboxRequest
from pants.core.util_rules.partitions import Partitions, PartitionMetadata
from pants.engine.addresses import Addresses
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import FilespecMatcher, Snapshot, Address, AddressInput
from pants.engine.internals.selectors import Get
from pants.engine.rules import rule, collect_rules
from pants.engine.target import Targets, FieldSetsPerTarget, FieldSetsPerTargetRequest
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem


"""
ByoTool(
    goal="lint",
    options_scope='byo_flake8',
    name="byo_Flake8",
    help="Flake8 linter using the flake8 you have specified in a resolve",
    executable=PythonToolExecutable(
        main=ConsoleScript("flake8"),
        requirements=["flake8>=5.0.4,<7"],
        resolve="byo_flake8",
    ),
    file_glob_include=["**/*.py"],
    file_glob_exclude=["pants-plugins/**"],
),
"""


class ByoTool(Subsystem):
    options_scope = 'byotool'
    name = 'ByoTool'
    help = 'Bring your own Tool'

    skip = SkipOption('lint')
    runnable = '//:flake8'
    file_glob_include = ["**/*.py"]
    file_glob_exclude = ["pants-plugins/**"]


class ByoToolRequest(LintFilesRequest):
    tool_subsystem = ByoTool


@rule
async def partition_inputs(
        request: ByoToolRequest.PartitionRequest,
        subsystem: ByoTool
) -> Partitions[str, PartitionMetadata]:
    if subsystem.skip:
        return Partitions()

    # import pydevd_pycharm
    # pydevd_pycharm.settrace('localhost', port=5678, stdoutToServer=True, stderrToServer=True)

    matching_filepaths = FilespecMatcher(
        includes=subsystem.file_glob_include, excludes=subsystem.file_glob_exclude
    ).matches(request.files)

    return Partitions.single_partition(sorted(matching_filepaths))


@rule
async def run_byotool(request: ByoToolRequest.Batch,
                      subsystem: ByoTool) -> LintResult:
    sources_snapshot = await Get(Snapshot, PathGlobs(request.elements))

    runnable_address_str = subsystem.runnable
    runnable_address = await Get(Address, AddressInput,
                                 AddressInput.parse(
                                    runnable_address_str,
                                     description_of_origin=f"ByoTool runnable target"
                                 ))

    # raise Exception('blah!')

    addresses = Addresses((runnable_address,))
    addresses.expect_single()

    runnable_targets = await Get(Targets, Addresses, addresses)
    import pydevd_pycharm
    pydevd_pycharm.settrace('localhost', port=5678, stdoutToServer=True, stderrToServer=True)
    field_sets = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(RunFieldSet, runnable_targets)
    )
    import pydevd_pycharm
    pydevd_pycharm.settrace('localhost', port=5678, stdoutToServer=True, stderrToServer=True)

    run_request = await Get(
        RunInSandboxRequest, {environment_name: EnvironmentName, run_field_set: RunFieldSet}
    )

    run_field_set: RunFieldSet = field_sets.field_sets[0]

    return LintResult(PANTS_SUCCEEDED_EXIT_CODE, "success", "", "byotool")

# A requirement is runnable: //:flake8 is the name of the target. Could use it.

def rules():
    return [
        *collect_rules(),
        *ByoToolRequest.rules()
    ]