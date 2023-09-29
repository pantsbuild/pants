from dataclasses import dataclass

from pants.backend.shell.target_types import ShellSourceField
from pants.core.goals.lint import AbstractLintRequest, LintTargetsRequest, LintResult
from pants.core.goals.multi_tool_goal_helper import SkippableSubsystem
from pants.core.target_types import FileSourceField
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel


class AutoLintSubsystem(Subsystem):
    options_scope = "autolint"
    skip = SkipOption("lint")
    name = "AutoLint"
    help = "An experimental simplified lint"


@dataclass(frozen=True)
class AutoLintFieldSet(FieldSet):
    required_fields = (FileSourceField,)
    source: FileSourceField

class AutoLintRequest(LintTargetsRequest):
    tool_subsystem = AutoLintSubsystem
    # partitioner_type = PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION
    field_set_type = AutoLintFieldSet


def target_types():
    return []


@rule
async def run_autolint(
        request: AutoLintRequest.Batch,
        bash: BashBinary,
) -> LintResult:

    sources = await Get(
        SourceFiles,
        SourceFilesRequest(field_set.source for field_set in request.elements),
    )

    input_digest = sources.snapshot.digest

    import pantsdebug; pantsdebug.settrace_5678()
    process_result = await Get(
        FallibleProcessResult,
        Process(
            # argv=(bash.path, "-c", "/opt/homebrew/bin/shellcheck", "scripts/stuff.sh"),
            argv=("/opt/homebrew/bin/shellcheck", *sources.files),
            # we can use sources.files to have all the files.
            input_digest=input_digest,
            description=f"Run Autolint on {request.partition_metadata.description}",
            level=LogLevel.INFO,
            # env={"CHROOT": "{chroot}"}
        ),
    )
    return LintResult.create(request, process_result)


def rules():
    return [
        *collect_rules(),
        *AutoLintRequest.rules()
    ]
