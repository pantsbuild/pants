from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Tuple, Type

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript, PythonSourceField
from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest
from pants.core.goals.lint import LintResult, LintResults, LintTargetsRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import SubsystemRule, rule
from pants.engine.target import Dependencies, FieldSet
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class MetalintTool(PythonToolBase):
    args: ArgsListOption


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


ArgvMaker = Callable[[MetalintTool, Tuple[str, ...]], Iterable[str]]


def no_argv(tool: MetalintTool, files: Tuple[str, ...]):
    """Helper for tools that just run without any args"""
    return []


def files_argv(tool: MetalintTool, files: Tuple[str, ...]):
    """Helper for tools that just take a list of files to run against"""
    return files


def make_linter(
    python_tool: Type[MetalintTool],
    linter_name,
    argv_maker: ArgvMaker,
    MetalintFieldSet: Optional[Type[FieldSet]] = None,
    MetalintRequest: Optional[Type[LintTargetsRequest]] = None,
):

    if not MetalintFieldSet:

        @dataclass(frozen=True)
        class MetalintFieldSet(FieldSet):
            required_fields = (PythonSourceField,)

            sources: PythonSourceField
            dependencies: Dependencies

    if not MetalintRequest:

        class MetalintRequest(LintTargetsRequest):
            field_set_type = MetalintFieldSet
            name = linter_name

    @rule(level=LogLevel.DEBUG)
    async def run_metalint(
        request: MetalintRequest, metalint: python_tool
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

        argv = argv_maker(metalint, sources.snapshot.files)
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

    return Metalint(python_tool, MetalintFieldSet, MetalintRequest, run_metalint)


def rules():
    class RadonTool(MetalintTool):
        options_scope = "radon"
        name = "radon"
        help = """Radon is a Python tool which computes various code metrics."""

        default_version = "radon==5.1.0"
        default_main = ConsoleScript("radon")

        register_interpreter_constraints = True
        default_interpreter_constraints = ["CPython>=3.7"]

        args = ArgsListOption(example="--no-assert")

    def radon_cc_args(tool: MetalintTool, files: Tuple[str, ...]):
        return ["cc"] + ["-s", "--total-average", "--no-assert", "-nb"] + list(files)

    radoncc = make_linter(RadonTool, "radoncc", radon_cc_args)

    def radon_mi_args(tool: MetalintTool, files: Tuple[str, ...]):
        return ["mi"] + ["-m", "-s"] + list(files)

    radonmi = make_linter(RadonTool, "radonmi", radon_mi_args)

    class VultureTool(MetalintTool):
        options_scope = "vulture"
        name = "Vulture"
        help = """Vulture finds unused code in Python programs"""

        default_version = "vulture==2.5"
        default_main = ConsoleScript("vulture")

        register_interpreter_constraints = True
        default_interpreter_constraints = ["CPython>=3.7"]

        args = ArgsListOption(example="--min-confidence 95")

    def vulture_args(tool: VultureTool, files: Tuple[str, ...]):
        return tool.args + files

    vulture = make_linter(VultureTool, "vulture", vulture_args)

    return [*radoncc.rules(), *radonmi.rules(), *vulture.rules()]
