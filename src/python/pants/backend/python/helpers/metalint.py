from dataclasses import dataclass
from typing import Callable, Type

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript, PythonSourceField
from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest
from pants.core.goals.lint import LintResult, LintResults, LintTargetsRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import SubsystemRule, collect_rules, rule
from pants.engine.target import Dependencies, FieldSet
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class Metalint:
    tool: Type[PythonToolBase]
    fs: Type[FieldSet]
    lint_req: Type[LintTargetsRequest]
    run_rule: Callable

    def rules(self):
        return [
            SubsystemRule(self.tool),
            UnionRule(LintTargetsRequest, self.lint_req),
            self.run_rule,
        ]


def mk(linter_name, binary_name, metalint_argv):
    class MetalintTool(PythonToolBase):
        options_scope = linter_name
        name = linter_name
        help = """ """

        default_version = "radon==5.1.0"
        default_main = ConsoleScript(binary_name)

        register_interpreter_constraints = True
        default_interpreter_constraints = ["CPython>=3.7"]

        args = ArgsListOption(example="")

    @dataclass(frozen=True)
    class MetalintFieldSet(FieldSet):
        required_fields = (PythonSourceField,)

        sources: PythonSourceField
        dependencies: Dependencies

    class MetalintRequest(LintTargetsRequest):
        field_set_type = MetalintFieldSet
        name = linter_name

    @rule(level=LogLevel.DEBUG)
    async def run_metalint(
            request: MetalintRequest, metalint: MetalintTool
    ) -> LintResults:
        metalint_pex = Get(
            Pex,
            PexRequest(
                output_filename=f"{linter_name}.pex",
                internal_only=True,
                requirements=metalint.pex_requirements(),
                interpreter_constraints=metalint.interpreter_constraints,
                main=metalint.main,
            ),
        )

        sources_request = Get(
            SourceFiles,
            SourceFilesRequest(field_set.sources for field_set in request.field_sets),
        )

        downloaded_metalint, sources = await MultiGet(metalint_pex, sources_request)

        input_digest = await Get(
            Digest,
            MergeDigests(
                (
                    downloaded_metalint.digest,
                    sources.snapshot.digest,
                )
            ),
        )

        argv = [*metalint_argv, *sources.snapshot.files]
        process_result = await Get(
            FallibleProcessResult,
            PexProcess(
                downloaded_metalint,
                argv=argv,
                input_digest=input_digest,
                description=f"Run {linter_name} on {pluralize(len(request.field_sets), 'file')}.",
                level=LogLevel.DEBUG,
            ),
        )
        result = LintResult.from_fallible_process_result(process_result)
        return LintResults([result], linter_name=request.name)

    return Metalint(MetalintTool, MetalintFieldSet, MetalintRequest, run_metalint)


def rules():
    radon_cc = [
        "cc",
        "-s",
        "--total-average",
        "--no-assert",
        "-n",
    ]
    radoncc = mk("radoncc", "radon", radon_cc)
    radon_mi = [
        "mi", "-m", "-s",
    ]
    radonmi = mk("radonmi", "radon", radon_mi)

    return [*radoncc.rules(), *radonmi.rules()]
