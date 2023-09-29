from dataclasses import dataclass

from pants.core.goals.lint import LintTargetsRequest, LintResult
from pants.core.target_types import FileSourceField
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel


# class AlternativeSubsystem(Subsystem):
#     options_scope = "alt"
#     skip = SkipOption("lint")
#     name = "AutoLint"
#     help = "An experimental simplified lint"


AutoLintSubsystem = type(Subsystem)('AutoLintSubsystem', (Subsystem,), dict(
    options_scope="autolint",
    skip=SkipOption("lint"),
    name="AutoLint",
    help="An experimental simplified lint",
    _dynamic_subsystem=True,
))

AutoLintSubsystem.__module__ = __name__

import inspect
# import pantsdebug; pantsdebug.settrace_5678()
# src_lines, k = inspect.getsourcelines(AutoLintSubsystem)
# print(srclines[0], k)


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
            # argv=("/opt/homebrew/bin/markdownlint", *sources.files),
            # we can use sources.files to have all the files.
            input_digest=input_digest,
            description=f"Run Autolint on {request.partition_metadata.description}",
            level=LogLevel.INFO,
            # env={"PATH": "/opt/homebrew/bin/"}
        ),
    )
    return LintResult.create(request, process_result)


def rules():
    return [
        *collect_rules(),
        *AutoLintRequest.rules()
    ]
