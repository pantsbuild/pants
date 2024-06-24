from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.subsystems.setup import PythonSetup
from pants.core.goals.lint import REPORT_DIR, LintRequest, LintResult, LintResults
from pants.util.logging import LogLevel
from pants.engine.unions import UnionRule
from pants.engine.rules import collect_rules
from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix
from pants.core.goals.lint import LintRequest
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.process import FallibleProcessResult
from pants.util.strutil import pluralize

from pants.backend.python.lint.import_lint.subsystem import ImportLinter, ImportLintercheckFieldSet

class ImportLinterRequest(LintRequest):
    field_set_type = ImportLintercheckFieldSet

@dataclass(frozen=True)
class ImportLinterPartition:
    field_sets: Tuple[ImportLintercheckFieldSet, ...]
    interpreter_constraints: InterpreterConstraints

def generate_argv(source_files: SourceFiles, flake8: ImportLinter) -> Tuple[str, ...]:
    args = []
    if flake8.config:
        args.append(f"--config={flake8.config}")
    args.extend(flake8.args)
    args.extend(source_files.files)
    return tuple(args)

@rule(level=LogLevel.DEBUG)
async def flake8_lint_partition(partition: ImportLinterPartition, flake8: ImportLinter) -> LintResult:
    flake8_pex_get = Get(
        VenvPex,
        PexRequest(
            output_filename="importLinter.pex",
            internal_only=True,
            requirements=flake8.pex_requirements(),
            interpreter_constraints=partition.interpreter_constraints,
            main=flake8.main,
        ),
    )
    config_files_get = Get(ConfigFiles, ConfigFilesRequest, flake8.config_request)
    source_files_get = Get(
        SourceFiles, SourceFilesRequest(field_set.sources for field_set in partition.field_sets)
    )
    # Ensure that the empty report dir exists.
    report_directory_digest_get = Get(Digest, CreateDigest([Directory(REPORT_DIR)]))
    flake8_pex, config_files, report_directory, source_files = await MultiGet(
        flake8_pex_get, config_files_get, report_directory_digest_get, source_files_get
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (source_files.snapshot.digest, config_files.snapshot.digest, report_directory)
        ),
    )

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            flake8_pex,
            #argv=generate_argv(source_files, flake8),
            #argv=["--config=.importlinter"],
            input_digest=input_digest,
            output_directories=(REPORT_DIR,),
            description=f"Run Flake8 on {pluralize(len(partition.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    report = await Get(Digest, RemovePrefix(result.output_digest, REPORT_DIR))
    return LintResult.from_fallible_process_result(
        result,
        partition_description=str(sorted(str(c) for c in partition.interpreter_constraints)),
        report=report,
    )


@rule(desc="Import Linter", level=LogLevel.DEBUG)
async def run_import_linter(
    request: ImportLinterRequest, import_linter: ImportLinter, python_setup: PythonSetup
) -> LintResults:
    """if import_linter.skip:
        return LintResults([], linter_name="Import-linter")"""

    constraints_to_field_sets = InterpreterConstraints.group_field_sets_by_constraints(
        request.field_sets, python_setup
    )
    partitioned_results = await MultiGet(
        Get(LintResult, ImportLinterPartition(partition_field_sets, partition_compatibility))
        for partition_compatibility, partition_field_sets in constraints_to_field_sets.items()
    )
    return LintResults(partitioned_results, linter_name="Import-linter")

def rules():
    return [
        *collect_rules(),
        UnionRule(LintRequest, ImportLinterRequest),
        *pex.rules()
    ]
