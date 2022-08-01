"""
Helper to rapidly incorporate Linters into pants.
TODO:
- parse output ?
"""
import functools
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Tuple, Type

from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import (
    ExportToolOption,
    PythonToolBase,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import ConsoleScript, PythonSourceField
from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest
from pants.core.goals.generate_lockfiles import (
    DEFAULT_TOOL_LOCKFILE,
    GenerateToolLockfileSentinel,
)
from pants.core.goals.lint import LintResult, LintResults, LintTargetsRequest
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import SubsystemRule, rule
from pants.engine.target import Dependencies, FieldSet
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize, softwrap


class MetalintTool(PythonToolBase):
    args: ArgsListOption

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7"]

    export = ExportToolOption()

    register_lockfile = True
    default_lockfile_resource = ("", "")  # shim
    default_lockfile_url = "hihello"  # shim

    skip = SkipOption("lint")

    config = FileOption(
        "--config",
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to a config file for {cls.options_scope}
            """
        ),
    )

    config_discovery = BoolOption(
        "--config-discovery",
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include any relevant config files during
            runs (`.pylintrc`, `pylintrc`, `pyproject.toml`, and `setup.cfg`).

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )

    @property
    def lockfile(self) -> str:
        shim_lockfile = f"{self.options_scope}.lock"
        if not self._lockfile or self._lockfile == DEFAULT_TOOL_LOCKFILE:
            return shim_lockfile
        return self._lockfile

    def config_request(self) -> ConfigFilesRequest:
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_content={"pyproject.toml": b"[tool.vulture"},
        )


@functools.lru_cache  # functools.cache is python 3.8, and doesn't have a maxsize
def make_export_rules(python_tool: Type[PythonToolBase]):
    class MetalintExportSentinel(ExportPythonToolSentinel):
        ...

    @rule(level=LogLevel.DEBUG)
    def metalint_export(
        _: MetalintExportSentinel, tool: python_tool
    ) -> ExportPythonTool:
        return ExportPythonTool(
            resolve_name=tool.options_scope,
            pex_request=tool.to_pex_request(),
        )

    return MetalintExportSentinel, metalint_export


@functools.lru_cache
def make_lockfile_rules(python_tool: Type[PythonToolBase]):
    class MetalintGenerateToolLockfileSentinel(GenerateToolLockfileSentinel):
        resolve_name = python_tool.options_scope

    @rule(level=LogLevel.DEBUG)
    def metalint_lockfile(
        _: MetalintGenerateToolLockfileSentinel,
        tool: python_tool,
        python_setup: PythonSetup,
    ) -> GeneratePythonLockfile:
        return GeneratePythonLockfile.from_tool(
            tool, use_pex=python_setup.generate_lockfiles_with_pex
        )

    return MetalintGenerateToolLockfileSentinel, metalint_lockfile


@dataclass(frozen=True)
class Metalint:
    tool: Type[PythonToolBase]
    fs: Type[FieldSet]
    lint_req: Type[LintTargetsRequest]
    export_sentinel: Type[ExportPythonToolSentinel]
    export_rule: Callable
    lockfile_sentinel: Type[GenerateToolLockfileSentinel]
    lockfile_rule: Callable
    run_rule: Callable

    def rules(self):
        return [
            SubsystemRule(self.tool),
            UnionRule(LintTargetsRequest, self.lint_req),
            self.export_rule,
            UnionRule(ExportPythonToolSentinel, self.export_sentinel),
            self.lockfile_rule,
            UnionRule(GenerateToolLockfileSentinel, self.lockfile_sentinel),
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

    MetalintExportSentinel, metalint_export = make_export_rules(python_tool)

    MetalintGenerateToolLockfileSentinel, metalint_lockfile = make_lockfile_rules(
        python_tool
    )

    @rule(level=LogLevel.DEBUG)
    async def run_metalint(
        request: MetalintRequest, metalint: python_tool
    ) -> LintResults:
        if metalint.skip:
            return LintResults([], linter_name=request.name)

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

        config_files_get = Get(
            ConfigFiles,
            ConfigFilesRequest,
            metalint.config_request(),
        )

        downloaded_metalint, sources, config_files = await MultiGet(
            metalint_pex, sources_request, config_files_get
        )

        input_digest = await Get(
            Digest,
            MergeDigests(
                (
                    downloaded_metalint.digest,
                    sources.snapshot.digest,
                    config_files.snapshot.digest,
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

    return Metalint(
        python_tool,
        MetalintFieldSet,
        MetalintRequest,
        MetalintExportSentinel,
        metalint_export,
        MetalintGenerateToolLockfileSentinel,
        metalint_lockfile,
        run_metalint,
    )


def rules():
    class RadonTool(MetalintTool):
        options_scope = "radon"
        name = "radon"
        help = """Radon is a Python tool which computes various code metrics."""

        default_version = "radon==5.1.0"
        default_main = ConsoleScript("radon")

        args = ArgsListOption(example="--no-assert")

        def config_request(self) -> ConfigFilesRequest:
            """https://radon.readthedocs.io/en/latest/commandline.html#radon-configuration-files"""
            return ConfigFilesRequest(
                specified=self.config,
                specified_option_name=f"[{self.options_scope}].config",
                discovery=self.config_discovery,
                check_existence=["radon.cfg"],
                check_content={"setup.cfg": b"[radon]"},
            )

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

        args = ArgsListOption(example="--min-confidence 95")

    def vulture_args(tool: VultureTool, files: Tuple[str, ...]):
        return tool.args + files

    vulture = make_linter(VultureTool, "vulture", vulture_args)

    return [
        *radoncc.rules(),
        *radonmi.rules(),
        *vulture.rules(),
    ]
